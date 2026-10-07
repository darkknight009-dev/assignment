"""Build the generated report DOCX from the uploaded template.

Approach: the template's fixed wording is preserved exactly; only
``[[PLACEHOLDER]]`` spans are replaced.  Generated section bodies are
inserted directly below their template headings, each carrying a process
control marker and provenance references.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import DRAFT_BANNER, Evidence, SectionContent
from .parsers import PLACEHOLDER_PATTERN

PROCESS_LABEL = {
    "deterministic": "Process control: deterministic / template-based",
    "rag": "Process control: RAG (retrieval over reference documents, sources cited)",
    "evidence": "Process control: evidence-based, deterministic processing",
    "ai": "Process control: AI-assisted narrative (fact-checked)",
    "deterministic (AI unavailable)": "Process control: deterministic (AI unavailable; see notes)",
    "deterministic (AI draft discarded)": "Process control: deterministic (AI draft discarded on fact check; see notes)",
}

_WML = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def build_report_docx(bundle, sections: list[SectionContent], evidence: Evidence,
                      attachment_labels: dict[str, str], att_index_text: str,
                      out_path: Path) -> tuple[list[str], list[str]]:
    """Write the report DOCX. Returns ``(placeholders_used, unfilled)``."""
    from docx import Document

    doc = Document(str(bundle.template_path))

    used: set[str] = set()
    unfilled: set[str] = set()

    proto = bundle.protocol
    mapping: dict[str, str] = {
        "PROTOCOL_ID": proto.protocol_id,
        "TITLE": proto.title,
        "COMPONENT": proto.component,
        "REVISION": proto.revision,
        "DATE": proto.date,
        "TEST_METHOD": proto.test_method,
        "UNIT": proto.units,
        "LOWER_LIMIT": _g(proto.lower_limit),
        "UPPER_LIMIT": _g(proto.upper_limit),
        "DRAFT_BANNER": DRAFT_BANNER,
        "GENERATED_AT": _now(),
    }

    # 1) fill placeholders in the template's own paragraphs -------------------
    for para in doc.paragraphs:
        _fill_placeholders(para, mapping, used, unfilled)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _fill_placeholders(para, mapping, used, unfilled)

    # 2) inject generated content under each section heading -----------------
    bodies = {s.key: s for s in sections}
    headings = [p for p in doc.paragraphs
                if p.style is not None and p.style.name.startswith("Heading") and p.text.strip()]

    for heading_para in headings:
        sec = _match_section(heading_para.text.strip(), bodies)
        if sec is None:
            continue
        _clear_after_heading(doc, heading_para)
        _write_section(doc, heading_para, sec, evidence)

    # 3) attachment index + validation appendix (append at end) ---------------
    doc.add_heading("Attachment index", level=1)
    for line in att_index_text.split("\n"):
        if line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line.strip():
            doc.add_paragraph(line)

    doc.add_heading("Validation summary (auto-generated)", level=1)
    doc.add_paragraph(
        "The full validation checklist is rendered in the application UI. "
        "Out-of-range and missing-evidence findings are never removed by "
        "automated processing."
    )
    if evidence.failed:
        p = doc.add_paragraph()
        run = p.add_run(f"{evidence.failed} result(s) out of range are preserved "
                        "verbatim in this report.")
        run.bold = True

    doc.save(str(out_path))
    return sorted(used), sorted(unfilled)


# ------------------------------------------------------------------ helpers --
class _Inserter:
    """Insert new block items sequentially after an anchor XML element."""

    def __init__(self, doc, anchor_element) -> None:
        self.doc = doc
        self.anchor = anchor_element

    def paragraph(self, text: str = "", style: str | None = None):
        p = self.doc.add_paragraph(text, style=style) if style else self.doc.add_paragraph(text)
        self.anchor.addnext(p._p)
        self.anchor = p._p
        return p

    def table(self, table):
        self.anchor.addnext(table._tbl)
        self.anchor = table._tbl
        return table


def _fill_placeholders(para, mapping, used: set, unfilled: set) -> None:
    for run in para.runs:
        for m in PLACEHOLDER_PATTERN.finditer(run.text):
            name = m.group(1)
            used.add(name)
            value = mapping.get(name)
            if value in (None, ""):
                unfilled.add(name)
                run.text = run.text.replace(m.group(0), f"[[{name}]] (NOT FILLED)")
            else:
                run.text = run.text.replace(m.group(0), str(value))


def _match_section(heading_text: str, bodies: dict[str, SectionContent]) -> SectionContent | None:
    h = heading_text.lower()
    for key, sec in bodies.items():
        k = key.lower()
        if k in h or h in k:
            return sec
    if "project information" in h:
        return bodies.get("Project information and fixed statements")
    if "method" in h:
        return bodies.get("Test method and reference guidance")
    if "results" in h:
        return bodies.get("Results and evidence")
    if "summary" in h:
        return bodies.get("Summary and observations")
    return None


def _clear_after_heading(doc, heading_para) -> None:
    """Remove template body content between this heading and the next heading."""
    body = doc.element.body
    start = heading_para._p
    removing = False
    for child in list(body):
        if child is start:
            removing = True
            continue
        if removing:
            if child.tag == f"{_WML}p":
                style_el = child.find(f".//{_WML}pStyle")
                if style_el is not None and style_el.get(f"{_WML}val", "").startswith("Heading"):
                    break
            if child.tag == f"{_WML}sectPr":
                break
            body.remove(child)


def _write_section(doc, heading_para, sec: SectionContent, evidence: Evidence) -> None:
    from docx.shared import Pt, RGBColor

    ins = _Inserter(doc, heading_para._p)

    # process control marker (exact match first, then first-word fallback)
    label = PROCESS_LABEL.get(sec.process) or PROCESS_LABEL.get(
        sec.process.split(" ")[0], f"Process control: {sec.process}")
    p = ins.paragraph(label)
    run = p.runs[0] if p.runs else p.add_run("")
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # body lines
    for raw in sec.body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if sec.key == "Project information and fixed statements":
                ins.paragraph("")
            continue
        if line.startswith("- "):
            ins.paragraph(line[2:], style="List Bullet")
        else:
            ins.paragraph(line)

    # results table for the evidence section
    if sec.key == "Results and evidence":
        _add_results_table(ins, evidence)

    # citations as trailing note
    if sec.citations:
        p = ins.paragraph("Sources: " + "; ".join(c.reference for c in sec.citations))
        for r in p.runs:
            r.italic = True
            r.font.size = Pt(8.5)

    # warnings
    for w in sec.warnings:
        p = ins.paragraph("Note: " + w)
        for r in p.runs:
            r.italic = True
            r.font.color.rgb = RGBColor(0x99, 0x66, 0x00)


def _add_results_table(ins: _Inserter, evidence: Evidence) -> None:
    from docx.shared import RGBColor

    table = ins.doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(["Sample ID", "Measurement", "Unit", "Verdict", "CSV row"]):
        hdr[i].text = h
        if hdr[i].paragraphs[0].runs:
            hdr[i].paragraphs[0].runs[0].bold = True
    for ev in evidence.evaluations:
        row = table.add_row().cells
        row[0].text = str(ev["sample_id"])
        row[1].text = f"{ev['measurement_display']} {ev['unit']}".strip()
        row[2].text = str(ev["unit"])
        row[3].text = str(ev["verdict"])
        row[4].text = f"row {ev['row_number']}"
    for i, ev in enumerate(evidence.evaluations, start=1):
        if ev["verdict"] == "Fail":
            for cell in table.rows[i].cells:
                for para in cell.paragraphs:
                    for r in para.runs:
                        r.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
                        r.bold = True
    ins.table(table)


def _g(v: float | None) -> str:
    return "" if v is None else f"{v:g}"


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")
