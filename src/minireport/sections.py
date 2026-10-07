"""Builders for the four report sections and the attachment index section.

Each builder returns a :class:`SectionContent` whose ``process`` field states
which process controls the section (deterministic / rag / evidence / ai) --
the report shows this explicitly, per the assignment.

The AI narrative is strictly downstream of the deterministic evidence: it may
summarise verified results and retrieved guidance, but every number it writes
must pass the fact guard, and out-of-range values are never reworded into
successes.
"""

from __future__ import annotations

import os

from .evidence import missing_measurement_ids, out_of_range_ids
from .factguard import check_text, collect_allowed_numbers
from .models import Citation, Evidence, Protocol, SectionContent, WarningItem
from .retrieval import LocalIndex, RetrievalResult

# Queries driving retrieval.  The second group targets reporting/acceptance
# guidance rather than the method itself, so citations cover both.
METHOD_QUERIES = [
    "torque wrench calibration test method procedure",
    "sample preparation torque application rate acceptance",
    "measurement uncertainty compliance reporting",
]
REPORTING_QUERIES = [
    "report structure summary results pass fail guidance",
    "acceptance criteria source of truth reference",
]


def build_project_info(bundle, evidence, attachments_label: dict[str, str]) -> SectionContent:
    """Section 1: deterministic template fill from structured inputs."""
    proto = bundle.protocol
    missing_bits = []
    if not proto.protocol_id:
        missing_bits.append("protocol_id")
    if not proto.date:
        missing_bits.append("protocol date")
    warnings = []
    if missing_bits:
        warnings.append("Missing structured inputs: " + ", ".join(missing_bits))

    att_lines = []
    for path, label in attachments_label.items():
        name = path.name if hasattr(path, "name") and not isinstance(path, str) else str(path)
        att_lines.append(f"- {label}: {name}")
    for name in bundle.missing_expected_attachments():
        att_lines.append(f"- (missing) {name} -- not supplied; flagged in validation")

    body = [
        f"Protocol ID: {proto.protocol_id or '[[PROTOCOL_ID]]'}",
        f"Title: {proto.title or '(not provided)'}",
        f"Component: {proto.component or '(not provided)'}",
        f"Protocol revision: {proto.revision or '(not provided)'}",
        f"Protocol date: {proto.date or '(not provided)'}",
        f"Test method: {proto.test_method or '(not provided)'}",
        f"Acceptance criterion: {_criteria_text(proto)}",
        "",
        "Attachments supplied with this report:",
        *att_lines,
    ]
    return SectionContent(
        key="Project information and fixed statements",
        process="deterministic",
        body="\n".join(body),
        warnings=warnings,
    )


def _criteria_text(proto: Protocol) -> str:
    low = "open" if proto.lower_limit is None else f"{proto.lower_limit:g}"
    high = "open" if proto.upper_limit is None else f"{proto.upper_limit:g}"
    base = f"{proto.test_method or 'Measurement'} result must be within {low} to {high} {proto.units}".strip()
    if proto.criteria_text:
        base += f" ({proto.criteria_text})"
    return base + "."


def build_method_section(index: LocalIndex) -> SectionContent:
    """Section 2: RAG over the reference documents, with source citations."""
    hits = index.search_per_topic(METHOD_QUERIES + REPORTING_QUERIES, k_per_topic=2)
    top = hits[:4]
    lines = []
    citations: list[Citation] = []
    if not top:
        return SectionContent(
            key="Test method and reference guidance",
            process="rag",
            body="No reference documents were available for retrieval. "
                 "Method description must be reviewed manually before use.",
            warnings=["No reference content retrieved; section cannot be completed from sources."],
        )
    for hit in top:
        lines.append(f"- {hit.chunk.text} [{hit.chunk.source} {hit.chunk.location}]")
        citations.append(
            Citation(source=hit.chunk.source, reference=f"{hit.chunk.source} {hit.chunk.location}",
                     text=hit.chunk.text, score=round(hit.score, 4))
        )
    body = (
        "The following statements are retrieved verbatim from the supplied reference "
        "documents; each is cited to its source file and location.\n"
        + "\n".join(lines)
    )
    return SectionContent(key="Test method and reference guidance", process="rag",
                          body=body, citations=citations)


def build_results_section(bundle, evidence: Evidence) -> SectionContent:
    """Section 3: evidence-based, deterministic processing of the CSV."""
    proto = bundle.protocol
    missing = missing_measurement_ids(evidence)
    oor = out_of_range_ids(evidence)

    lines = [
        f"Raw data source: results.csv ({evidence.total} rows), evaluated against the "
        f"protocol acceptance range [{_fmt(proto.lower_limit)}, {_fmt(proto.upper_limit)}] {proto.units}.",
        "Pass/Fail is calculated deterministically by the application; no AI involvement.",
        "",
    ]
    for ev in evidence.evaluations:
        flag = ""
        if ev["verdict"] == "Fail":
            flag = "  ** OUT OF RANGE **"
        elif ev["verdict"] == "NO DATA":
            flag = "  ** MISSING MEASUREMENT **"
        lines.append(
            f"- {ev['sample_id']}: {ev['measurement_display']} {ev['unit']} -- {ev['verdict']} "
            f"({ev['detail']}) [results.csv row {ev['row_number']}]{flag}"
        )
    lines.append("")
    lines.append(f"Summary: {evidence.total} samples, {evidence.passed} passed, {evidence.failed} failed"
                 + (f", {len(missing)} without data" if missing else "") + ".")

    warnings = []
    if oor:
        warnings.append("Out-of-range values are reported exactly as measured and are not adjusted.")
    if missing:
        warnings.append("Samples without measurements are listed as NO DATA; no values were imputed.")
    return SectionContent(key="Results and evidence", process="evidence",
                          body="\n".join(lines), warnings=warnings)


def build_summary_section(bundle, evidence: Evidence, method_section: SectionContent,
                          index: LocalIndex, llm=None) -> SectionContent:
    """Section 4: AI-assisted narrative, verified and fact-checked."""
    proto = bundle.protocol
    oor = out_of_range_ids(evidence)
    miss = missing_measurement_ids(evidence)
    missing_att = bundle.missing_expected_attachments()

    hits = index.search_per_topic(
        ["acceptance criteria reporting guidance", "deviation handling out of specification results"],
        k_per_topic=2,
    )
    allowed = collect_allowed_numbers(evidence, proto, hits)

    facts = _fact_sheet(bundle, evidence)
    context_block = "\n\n".join(f"[{h.chunk.source} {h.chunk.location}] {h.chunk.text}" for h in hits[:3])

    ai_text: str | None = None
    ai_error = ""
    if llm is not None:
        try:
            ai_text = llm.summarise(facts, context_block)
        except Exception as exc:  # network, auth, quota... fall back cleanly
            ai_error = f"{type(exc).__name__}: {exc}"
            ai_text = None

    if ai_text:
        report = check_text(ai_text, allowed)
        if report.violations:
            return SectionContent(
                key="Summary and observations", process="ai", body="", ai_used=False,
                ai_discarded=True,
                ai_discard_reason="AI draft failed fact check on: " + "; ".join(report.violations[:5]),
                warnings=["AI draft discarded; deterministic summary used instead. "
                          + "Discarded draft is kept in the review UI for transparency."],
                citations=_citations_from(hits),
            )
        return SectionContent(
            key="Summary and observations", process="ai", body=ai_text, ai_used=True,
            citations=_citations_from(hits),
            warnings=["AI-assisted draft: verified against actual results and retrieved context; "
                      "edit before export."],
        )

    # Deterministic fallback (no LLM configured or AI errored)
    body = _deterministic_summary(bundle, evidence, oor, miss, missing_att)
    process = "deterministic (AI unavailable)" if llm is not None or ai_error else "deterministic"
    warnings = ["Generated without AI; fully deterministic."]
    if ai_error:
        warnings.append(f"AI call failed ({ai_error}); deterministic summary used.")
    return SectionContent(key="Summary and observations", process=process, body=body,
                          warnings=warnings, citations=_citations_from(hits))


def _deterministic_summary(bundle, evidence, oor, miss, missing_att) -> str:
    proto = bundle.protocol
    parts = [
        f"A total of {evidence.total} samples were evaluated against the protocol acceptance range "
        f"[{_fmt(proto.lower_limit)}, {_fmt(proto.upper_limit)}] {proto.units}: "
        f"{evidence.passed} passed and {evidence.failed} failed."
    ]
    if oor:
        parts.append(
            f"Out-of-range results were observed for {', '.join(oor)}. These values are reported as "
            "measured; no retest or adjustment was applied and no explanation is assumed."
        )
    else:
        parts.append("All measured results were within the acceptance range.")
    if miss:
        parts.append(
            f"No measurement was recorded for {', '.join(miss)}; these samples are excluded from the "
            "pass/fail statistics above and are flagged for follow-up."
        )
    if missing_att:
        parts.append(
            f"Expected attachment(s) not supplied: {', '.join(missing_att)}. The corresponding evidence "
            "is incomplete; this report must not be released until the attachment is provided."
        )
    parts.append("This summary is a draft generated from verified results and retrieved guidance; "
                 "review and edit before approval.")
    return " ".join(parts)


def _fact_sheet(bundle, evidence: Evidence) -> str:
    proto = bundle.protocol
    lines = [
        f"protocol_id: {proto.protocol_id}",
        f"component: {proto.component}",
        f"acceptance_range: [{proto.lower_limit}, {proto.upper_limit}] {proto.units}",
        "results:",
    ]
    for ev in evidence.evaluations:
        lines.append(
            f"- {ev['sample_id']}: measurement={ev['measurement_display']} {ev['unit']}, "
            f"verdict={ev['verdict']}, row={ev['row_number']}, observation={ev['observation'] or '(none)'}"
        )
    lines.append(f"totals: samples={evidence.total}, passed={evidence.passed}, failed={evidence.failed}")
    return "\n".join(lines)


def _citations_from(hits: list[RetrievalResult]) -> list[Citation]:
    return [Citation(source=h.chunk.source, reference=f"{h.chunk.source} {h.chunk.location}",
                     text=h.chunk.text, score=round(h.score, 4)) for h in hits[:3]]


def _fmt(v: float | None) -> str:
    return "open" if v is None else f"{v:g}"
