"""Build the generated report DOCX from the uploaded template.

Approach: the template's fixed wording is preserved exactly; only
``[[PLACEHOLDER]]`` spans are replaced.  Section bodies are written as bullet
or body paragraphs, each carrying its own provenance marker.
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
}


def build_report_docx(bundle, sections: list[SectionContent], evidence: Evidence,
                      attachment_labels: dict[str, str], att_index_text: str,
                      out_path: Path) -> tuple[list[str], list[str]]:
    """Write the report DOCX.

    Returns ``(placeholders_used, unfilled_placeholders)``.
    """
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document(str(bundle.template_path))

    # strip any template demo body left under the title page
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

    # 1) fill placeholders in the template's own paragraphs ------------------
    for para in doc.paragraphs:
        _fill_placeholders(para, mapping, used, unfilled)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _fill_placeholders(para, mapping, used, unfilled)

    # 2) locate section headings and inject generated content ---------------
    section_map: dict[str, object] = {}
    for para in doc.paragraphs:
        if para.style is not None and para.style.name.startswith("Heading"):
            section_map[para.text.strip()] = para

    bodies = {s.key: s for s in sections}

    for heading_text, para in list(section_map.items()):
        sec = _match_section(heading_text, bodies)
        if sec is None:
            continue
        _clear_after_heading(doc, para)
        _mark_process_control(doc, para, sec)

        if sec.key == "Project information and fixed statements":
            _write_project_info(doc, sec, mapping)
        elif sec.key == "Results and evidence":
            _write_results(doc, sec, evidence)
        elif sec.key == "Test method and reference guidance":
            _write_rag(doc, sec)
        else:
            _write_summary(doc, sec)

        _write_warnings(doc, sec)

    # 3) attachment index -----------------------------------------------------
    _write_attachment_index(doc, att_index_text, used, unfilled, mapping)

    # 4) validation appendix ---------------------------------------------------
    _write_validation_placeholder(doc, evidence)

    doc.save(str(out_path))
    return sorted(used), sorted(unfilled)


# ------------------------------------------------------------------ helpers --
def _fill_placeholders(para, mapping, used: set, unfilled: set) -> None:
    def replace_in_run(run) -> None:
        for m in PLACEHOLDER_PATTERN.finditer(run.text):
            name = m.group(1)
            used.add(name)
            value = mapping.get(name)
            if value in (None, ""):
                unfilled.add(name)
                run.text = run.text.replace(m.group(0), f"[[{name}]] (NOT FILLED)")
            else:
                run.text = run.text.replace(m.group(0), str(value))

    for run in para.runs:
        replace_in_run(run)


def _match_section(heading_text: str, bodies: dict[str, SectionContent]) -> SectionContent | None:
    """Match a template heading to a generated section, tolerating numbering."""
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
            if child.tag.endswith("}p"):
                style_el = child.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle")
                if style_el is not None and style_el.get(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", ""
                ).startswith("Heading"):
                    break
            if child.tag.endswith("}sectPr"):
                break
            body.remove(child)


def _mark_process_control(doc, heading_para, sec: SectionContent) -> None:
    from docx.shared import Pt, RGBColor

    p = doc.add_paragraph()
    run = p.add_run(PROCESS_LABEL.get(sec.process.split(" ")[0], f"Process control: {sec.process}"))
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    # move the marker paragraph directly after the heading
    heading_para._p.addnext(p._p)


def _write_project_info(doc, sec: SectionContent, mapping: dict[str, str]) -> None:
    p = doc.add_paragraph(sec.body)


def _write_rag(doc, sec: SectionContent) -> None:
    for line in sec.body.split("\n"):
        if not line.strip():
            continue
        if line.startswith("- "):
            p = doc.add_paragraph(line[2:], style="List Bullet")
        else:
            p = doc.add_paragraph(line)


def _write_results(doc, sec: SectionContent, evidence: Evidence) -> None:
    for line in sec.body.split("\n"):
        if not line.strip():
            continue
        if line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        else:
            doc.add_paragraph(line)
    # deterministic results table
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(["Sample ID", "Measurement", "Unit", "Verdict", "CSV row"]):
        hdr[i].text = h
        hdr[i].paragraphs[0].runs[0].bold = True
    for ev in evidence.evaluations:
        row = table.add_row().cells
        row[0].text = str(ev["sample_id"])
        row[1].text = f"{ev['measurement_display']} {ev['unit']}".strip()
        row[2].text = str(ev["unit"]) if not ev["unit"] else ""
        row[3].text = str(ev["verdict"])
        row[4].text = f"row {ev['row_number']}"
    _flag_failures(doc, table, evidence)


def _flag_failures(doc, table, evidence: Evidence) -> None:
    from docx.shared import RGBColor

    for i, ev in enumerate(evidence.evaluations, start=1):
        if ev["verdict"] == "Fail":
            for cell in table.rows[i].cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
                        run.bold = True


def _write_summary(doc, sec: SectionContent) -> None:
    if not sec.body:
        doc.add_paragraph("(AI draft discarded -- deterministic summary unavailable. See validation.)")
        return
    for para_text in sec.body.split("\n\n"):
        doc.add_paragraph(para_text.strip())


def _write_warnings(doc, sec: SectionContent) -> None:
    from docx.shared import RGBColor

    if not sec.warnings:
        return
    for w in sec.warnings:
        p = doc.add_paragraph()
        run = p.add_run("Note: " + w)
        run.italic = True
        run.font.color.rgb = RGBColor(0x99, 0x66, 0x00)


def _write_attachment_index(doc, att_index_text: str, used: set, unfilled: set, mapping: dict) -> None:
    doc.add_heading("Attachment index", level=1)
    for line in att_index_text.split("\n"):
        if line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line.strip():
            doc.add_paragraph(line)


def _write_validation_placeholder(doc, evidence: Evidence) -> None:
    doc.add_heading("Validation summary (auto-generated)", level=1)
    doc.add_paragraph(
        "The full validation checklist is rendered in the application UI and in the "
        "combined PDF. Out-of-range and missing-evidence findings are never removed "
        "by automated processing."
    )
    if evidence.failed:
        p = doc.add_paragraph()
        run = p.add_run(f"{evidence.failed} result(s) out of range are preserved verbatim in this report.")
        run.bold = True


def _g(v: float | None) -> str:
    return "" if v is None else f"{v:g}"


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")
