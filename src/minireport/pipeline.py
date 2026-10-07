"""End-to-end pipeline: inputs -> evidence -> sections -> artifacts.

``generate`` returns a :class:`GenerationResult` holding every produced
artifact plus the review data the UI needs (sections, checklist, provenance).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .evidence import build_evidence
from .inputs import load_inputs
from .models import DRAFT_BANNER, Evidence, SectionContent, WarningItem
from .retrieval import LocalIndex
from .report import build_report_docx
from .sections import (
    build_method_section,
    build_project_info,
    build_results_section,
    build_summary_section,
)
from .validation import build_checklist

# Stable attachment labels: Attachment A, B, ... in alphabetical file order.
LABELS = "ABCDEFGHIJKLMN"


@dataclass
class GenerationResult:
    output_dir: Path
    docx_path: Path
    xlsx_path: Path
    combined_pdf_path: Path
    zip_path: Path
    evidence: Evidence
    sections: list[SectionContent]
    checklist: list[WarningItem]
    attachment_labels: dict[str, str]  # filename -> label
    protocol: object = None  # Protocol object, for UI editing
    input_dir: Path | None = None  # where inputs were loaded from (edit flows rely on this)
    placeholders_used: list[str] = field(default_factory=list)
    unfilled_placeholders: list[str] = field(default_factory=list)
    ai_discarded_drafts: list[dict] = field(default_factory=list)

    def markdown_checklist(self) -> str:
        icon = {"error": "✗", "warning": "⚠", "info": "✓"}
        return "\n".join(f"- [{icon.get(i.severity, '·')}] {i.message}" for i in self.checklist)


def generate(input_dir: str | Path, output_dir: str | Path, llm=None) -> GenerationResult:
    """Run the full generation flow for one input folder."""
    bundle = load_inputs(input_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---- deterministic evidence (single source of truth) -------------------
    results = parse_results(bundle.results_csv_path)
    evidence = build_evidence(results, bundle.protocol)

    # ---- retrieval index over reference documents --------------------------
    index = LocalIndex()
    indexed_docs = 0
    for ref in bundle.references:
        indexed_docs += index.add_document(ref)

    # ---- attachment labels (Attachment A, B, ...) --------------------------
    attachment_labels = {p.name: f"Attachment {LABELS[i]}" for i, p in enumerate(bundle.attachments)}

    # ---- section builders (the four required approaches) -------------------
    sec_info = build_project_info(bundle, evidence, attachment_labels)
    sec_method = build_method_section(index)
    sec_results = build_results_section(bundle, evidence)
    sec_summary = build_summary_section(bundle, evidence, sec_method, index, llm=llm)
    sections = [sec_info, sec_method, sec_results, sec_summary]

    att_index_text = _attachment_index_text(bundle, attachment_labels, indexed_docs)

    # ---- artifacts ----------------------------------------------------------
    docx_path = out / "generated_report.docx"
    placeholders_used, unfilled = build_report_docx(
        bundle, sections, evidence, attachment_labels, att_index_text, docx_path
    )

    from .xlsx import build_workbook

    xlsx_path = out / "results_table.xlsx"
    build_workbook(evidence, bundle.protocol, xlsx_path)

    from .pdfbuild import build_combined_pdf, read_xlsx_rows

    combined_pdf_path = out / "combined_report.pdf"
    attachments_by_label = {label: str(bundle.directory / name) for name, label in attachment_labels.items()}
    build_combined_pdf(
        sections,
        evidence,
        bundle.protocol,
        read_xlsx_rows(xlsx_path),
        attachments_by_label,
        combined_pdf_path,
    )

    zip_path = out / "report_package.zip"
    _make_zip(zip_path, [docx_path, combined_pdf_path, xlsx_path, *bundle.attachments])

    checklist = build_checklist(bundle, evidence, unfilled_placeholders=unfilled)
    ai_discarded = []
    for s in sections:
        if s.ai_discarded:
            ai_discarded.append({"section": s.key, "reason": s.ai_discard_reason})

    return GenerationResult(
        output_dir=out,
        docx_path=docx_path,
        xlsx_path=xlsx_path,
        combined_pdf_path=combined_pdf_path,
        zip_path=zip_path,
        evidence=evidence,
        sections=sections,
        checklist=checklist,
        attachment_labels=attachment_labels,
        protocol=bundle.protocol,
        input_dir=Path(input_dir),
        placeholders_used=placeholders_used,
        unfilled_placeholders=unfilled,
        ai_discarded_drafts=ai_discarded,
    )


def parse_results(csv_path: Path):
    from .parsers import parse_results_csv

    return parse_results_csv(csv_path)


def _attachment_index_text(bundle, attachment_labels: dict[str, str], indexed_docs: int) -> str:
    lines = ["The following attachments are included and referenced by label in this report:"]
    for name, label in sorted(attachment_labels.items(), key=lambda kv: kv[1]):
        lines.append(f"- {label}: {name}")
    for name in bundle.missing_expected_attachments():
        lines.append(f"- (expected but missing): {name}")
    return "\n".join(lines)


def _make_zip(zip_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)


# ------------------------------------------------------------ edit & rebuild --
def regenerate_artifacts(result: GenerationResult, input_dir: str | Path) -> None:
    """Rebuild DOCX/PDF/XLSX/ZIP from a (possibly user-edited) result object."""
    out = Path(result.output_dir)
    bundle = load_inputs(input_dir)

    build_report_docx(
        bundle, result.sections, result.evidence, result.attachment_labels,
        _attachment_index_text(bundle, result.attachment_labels, 0), result.docx_path,
    )
    from .xlsx import build_workbook

    build_workbook(result.evidence, bundle.protocol, result.xlsx_path)

    from .pdfbuild import build_combined_pdf, read_xlsx_rows

    build_combined_pdf(
        result.sections,
        result.evidence,
        bundle.protocol,
        read_xlsx_rows(result.xlsx_path),
        {label: str(bundle.directory / name) for name, label in result.attachment_labels.items()},
        result.combined_pdf_path,
    )
    _make_zip(result.zip_path, [result.docx_path, result.combined_pdf_path,
                                result.xlsx_path, *bundle.attachments])


def apply_edits_and_regenerate(
    result: GenerationResult,
    input_dir: str | Path,
    *,
    new_lower: float,
    new_upper: float,
    sample_id: str,
    new_value: float,
    limit_changed: bool,
    value_changed: bool,
) -> GenerationResult:
    """Apply user edits to protocol limits / a measurement, then regenerate.

    Everything downstream of the evidence object is rebuilt, which is the
    consistency guarantee of the app: one decision point, many artifacts.
    """
    bundle = load_inputs(input_dir)
    proto = bundle.protocol
    if limit_changed:
        proto.lower_limit = new_lower
        proto.upper_limit = new_upper
        results = result.evidence.results
    else:
        results = result.evidence.results
        if value_changed:
            for r in results:
                if r.sample_id == sample_id:
                    r.measurement = new_value
                    r.raw_measurement = f"{new_value:g}"

    evidence = build_evidence(results, proto)
    index = LocalIndex()
    for ref in bundle.references:
        index.add_document(ref)

    attachment_labels = {p.name: f"Attachment {LABELS[i]}" for i, p in enumerate(bundle.attachments)}
    sec_info = build_project_info(bundle, evidence, attachment_labels)
    sec_method = build_method_section(index)
    sec_results = build_results_section(bundle, evidence)
    # keep any user-edited summary text if the situation is unchanged
    prev_summary = next((s for s in result.sections if s.key == "Summary and observations"), None)
    sec_summary = build_summary_section(bundle, evidence, sec_method, index, llm=None)
    if prev_summary is not None and not prev_summary.ai_discarded and prev_summary.ai_used:
        sec_summary.body = prev_summary.body
        sec_summary.process = prev_summary.process

    sections = [sec_info, sec_method, sec_results, sec_summary]
    att_index_text = _attachment_index_text(bundle, attachment_labels, 0)

    docx_path = Path(result.output_dir) / "generated_report.docx"
    _used, unfilled = build_report_docx(bundle, sections, evidence, attachment_labels,
                                        att_index_text, docx_path)
    from .xlsx import build_workbook
    from .pdfbuild import build_combined_pdf, read_xlsx_rows

    xlsx_path = Path(result.output_dir) / "results_table.xlsx"
    build_workbook(evidence, proto, xlsx_path)
    combined_pdf_path = Path(result.output_dir) / "combined_report.pdf"
    build_combined_pdf(
        sections, evidence, proto, read_xlsx_rows(xlsx_path),
        {label: str(bundle.directory / name) for name, label in attachment_labels.items()},
        combined_pdf_path,
    )
    zip_path = Path(result.output_dir) / "report_package.zip"
    _make_zip(zip_path, [docx_path, combined_pdf_path, xlsx_path, *bundle.attachments])

    checklist = build_checklist(bundle, evidence, unfilled_placeholders=unfilled)
    return GenerationResult(
        output_dir=Path(result.output_dir),
        docx_path=docx_path,
        xlsx_path=xlsx_path,
        combined_pdf_path=combined_pdf_path,
        zip_path=zip_path,
        evidence=evidence,
        sections=sections,
        checklist=checklist,
        attachment_labels=attachment_labels,
        protocol=proto,
        placeholders_used=_used,
        unfilled_placeholders=unfilled,
    )
