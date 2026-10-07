"""JSON API orchestration for the Next.js UI.

Wraps the same tested pipeline the CLI uses.  Each scenario/ai combination
gets a workspace holding the artifacts plus a ``state.json`` describing the
current protocol values, measurement rows and any user-edited summary — so
edit-and-regenerate works across separate bridge processes (each Next.js API
route call spawns a fresh interpreter).
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from pathlib import Path

from .evidence import build_evidence
from .inputs import load_inputs
from .llm import OpenRouterLLM
from .models import DRAFT_BANNER, Protocol, SampleResult, SectionContent, WarningItem
from .models import Citation
from .pipeline import (
    LABELS,
    GenerationResult,
    _attachment_index_text,
    _make_zip,
    generate,
)
from .report import build_report_docx
from .retrieval import LocalIndex
from .sections import (
    build_method_section,
    build_project_info,
    build_results_section,
    build_summary_section,
)
from .validation import build_checklist
from .xlsx import build_workbook
from .pdfbuild import build_combined_pdf, read_xlsx_rows

SCENARIOS: dict[str, str] = {
    "complete": "inputs",
    "failing": "inputs/demo_variants/failing",
    "incomplete": "inputs/demo_variants/incomplete",
}

CACHE_BASE = Path("/tmp/minireport/webcache")


def _workspace(scenario: str, ai: bool) -> Path:
    d = CACHE_BASE / f"{scenario}_{'ai' if ai else 'plain'}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------- generate ---
def run_scenario(scenario: str, ai: bool) -> dict:
    """Full generation for one demo scenario."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario}'")
    input_dir = SCENARIOS[scenario]
    ws = _workspace(scenario, ai)

    llm = OpenRouterLLM() if ai else None
    result = generate(input_dir, ws, llm=llm)

    bundle = load_inputs(input_dir)
    state = {
        "scenario": scenario,
        "ai": ai,
        "input_dir": input_dir,
        "protocol": _protocol_state(bundle),
        "results": [asdict(r) for r in result.evidence.results],
        "summary_text": next(
            s.body for s in result.sections if s.key == "Summary and observations"
        ),
        "summary_edited": False,
    }
    (ws / "state.json").write_text(json.dumps(state, indent=1))
    return _serialize(result, scenario, ai, bundle.protocol)


def _protocol_state(bundle) -> dict:
    p = bundle.protocol
    return {
        "protocol_id": p.protocol_id, "title": p.title, "component": p.component,
        "revision": p.revision, "date": p.date, "test_method": p.test_method,
        "units": p.units, "lower_limit": p.lower_limit, "upper_limit": p.upper_limit,
        "planned_sample_ids": p.planned_sample_ids,
        "expected_attachments": p.expected_attachments,
        "criteria_text": p.criteria_text, "source_path": p.source_path,
    }


# -------------------------------------------------------------- edit flows --
def apply_summary_edit(scenario: str, ai: bool, text: str) -> dict:
    state, ws = _load_state(scenario, ai)
    state["summary_text"] = text
    state["summary_edited"] = True
    (ws / "state.json").write_text(json.dumps(state, indent=1))
    result = _rebuild(state, ws)
    return _serialize(result, scenario, ai, _protocol_from(state))


def apply_edits(scenario: str, ai: bool, payload: dict) -> dict:
    state, ws = _load_state(scenario, ai)
    proto = state["protocol"]
    limit_changed = (
        payload.get("lower") is not None and float(payload["lower"]) != float(proto["lower_limit"] or 0)
    ) or (
        payload.get("upper") is not None and float(payload["upper"]) != float(proto["upper_limit"] or 0)
    )
    if payload.get("lower") is not None:
        proto["lower_limit"] = float(payload["lower"])
    if payload.get("upper") is not None:
        proto["upper_limit"] = float(payload["upper"])

    value_changed = bool(payload.get("value_changed")) and payload.get("sample_id")
    if value_changed:
        sid = payload["sample_id"]
        for row in state["results"]:
            if row["sample_id"] == sid:
                row["measurement"] = float(payload["value"])
                row["raw_measurement"] = f"{float(payload['value']):g}"

    if not limit_changed and not value_changed:
        raise ValueError("no edits supplied")
    (ws / "state.json").write_text(json.dumps(state, indent=1))
    result = _rebuild(state, ws)
    return _serialize(result, scenario, ai, _protocol_from(state))


def _load_state(scenario: str, ai: bool) -> tuple[dict, Path]:
    ws = _workspace(scenario, ai)
    f = ws / "state.json"
    if not f.exists():
        raise ValueError("generate first")
    return json.loads(f.read_text()), ws


def _protocol_from(state: dict) -> Protocol:
    return Protocol(**state["protocol"])


def _rebuild(state: dict, ws: Path) -> GenerationResult:
    """Deterministic full rebuild from persisted state (no AI call)."""
    proto = _protocol_from(state)
    bundle = load_inputs(state["input_dir"])
    # the edited protocol (limits etc.) must drive EVERY section and the
    # checklist, not just the verdict mathematics — otherwise the report
    # would show a stale range next to freshly computed verdicts.
    bundle.protocol = proto

    results = [SampleResult(**row) for row in state["results"]]
    evidence = build_evidence(results, proto)

    index = LocalIndex()
    for ref in bundle.references:
        index.add_document(ref)

    attachment_labels = bundle.attachment_labels if hasattr(bundle, "attachment_labels") else {
        p.name: f"Attachment {LABELS[i]}" for i, p in enumerate(bundle.attachments)
    }

    sec_info = build_project_info(bundle, evidence, attachment_labels)
    sec_method = build_method_section(index)
    sec_results = build_results_section(bundle, evidence)
    sec_summary = build_summary_section(bundle, evidence, sec_method, index, llm=None)
    if state.get("summary_edited"):
        sec_summary.body = state["summary_text"]
        sec_summary.process = "ai" if state.get("ai") else sec_summary.process
    sections = [sec_info, sec_method, sec_results, sec_summary]

    att_index_text = _attachment_index_text(bundle, attachment_labels, 0)
    docx_path = ws / "generated_report.docx"
    _used, unfilled = build_report_docx(bundle, sections, evidence, attachment_labels,
                                        att_index_text, docx_path)
    xlsx_path = ws / "results_table.xlsx"
    build_workbook(evidence, proto, xlsx_path)
    combined_pdf_path = ws / "combined_report.pdf"
    build_combined_pdf(
        sections, evidence, proto, read_xlsx_rows(xlsx_path),
        {label: str(bundle.directory / name) for name, label in attachment_labels.items()},
        combined_pdf_path,
    )
    zip_path = ws / "report_package.zip"
    _make_zip(zip_path, [docx_path, combined_pdf_path, xlsx_path, *bundle.attachments])

    checklist = build_checklist(bundle, evidence, unfilled_placeholders=unfilled)
    return GenerationResult(
        output_dir=ws,
        docx_path=docx_path,
        xlsx_path=xlsx_path,
        combined_pdf_path=combined_pdf_path,
        zip_path=zip_path,
        evidence=evidence,
        sections=sections,
        checklist=checklist,
        attachment_labels=attachment_labels,
        protocol=proto,
        input_dir=Path(state["input_dir"]),
    )


# --------------------------------------------------------------- serialize --
def _artifact_payload(path: Path) -> dict:
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _serialize(result: GenerationResult, scenario: str, ai: bool, proto: Protocol) -> dict:
    summary = next(s for s in result.sections if s.key == "Summary and observations")
    return {
        "scenario": scenario,
        "aiRequested": ai,
        "draftBanner": DRAFT_BANNER,
        "checklist": [
            {"severity": i.severity, "code": i.code, "message": i.message}
            for i in result.checklist
        ],
        "sections": [
            {
                "key": s.key,
                "process": s.process,
                "body": s.body,
                "citations": [c.reference for c in s.citations],
                "warnings": s.warnings,
                "aiUsed": s.ai_used,
                "aiDiscarded": s.ai_discarded,
                "aiDiscardReason": s.ai_discard_reason,
                "aiModel": s.ai_model,
                "aiAttempts": [list(a) for a in s.ai_attempts],
            }
            for s in result.sections
        ],
        "summaryEdited": _summary_edited_flag(result, scenario, ai),
        "artifacts": {
            "docx": _artifact_payload(result.docx_path),
            "xlsx": _artifact_payload(result.xlsx_path),
            "pdf": _artifact_payload(result.combined_pdf_path),
            "zip": _artifact_payload(result.zip_path),
        },
        "edits": {
            "lower": proto.lower_limit,
            "upper": proto.upper_limit,
            "samples": [e["sample_id"] for e in result.evidence.evaluations],
            "measurements": {e["sample_id"]: e["measurement"] for e in result.evidence.evaluations},
        },
        "engineNote": (
            "Pass/Fail decisions are computed once in minireport.evidence; DOCX, "
            "XLSX, PDF and the narrative all render from that single object."
        ),
    }


def _summary_edited_flag(result, scenario, ai) -> bool:
    ws = _workspace(scenario, ai)
    f = ws / "state.json"
    if f.exists():
        return bool(json.loads(f.read_text()).get("summary_edited"))
    return False
