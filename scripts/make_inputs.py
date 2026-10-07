"""Create the sample input set and the three demo-case variants.

Run:  python scripts/make_inputs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TEMPLATE_TEXT = [
    ("Title", 0, "[[DRAFT_BANNER]]"),
    ("Title", 0, "Inspection Report - [[TITLE]]"),
    ("Subtitle", 0, "Protocol [[PROTOCOL_ID]] - Revision [[REVISION]] - [[DATE]]"),
    ("Normal", 0,
     "This report was generated automatically from the approved protocol, the raw "
     "measurement data and the supplied reference documents. It is issued as a draft "
     "for review; the reviewer must verify all entries before approval."),
    ("Heading1", 0, "Project information and fixed statements"),
    ("Heading1", 0, "Test method and reference guidance"),
    ("Heading1", 0, "Results and evidence"),
    ("Heading1", 0, "Summary and observations"),
    ("Normal", 0,
     "Approval statement: This report is not valid for release until the reviewer has "
     "signed below. All automated findings must be dispositioned."),
    ("Normal", 0, "Reviewed by: ____________________    Date: ____________"),
]

PROTOCOL = """protocol_id: PROT-2026-014
title: Torque retention verification
component: HX-100 Heat Exchanger Mounting Bracket
revision: B
date: 2026-10-01
test_method: TQ-7 Torque Retention Test
unit: Nm
lower_limit: 45.0
upper_limit: 55.0
criteria: all samples within range
planned_samples:
- S-01
- S-02
- S-03
- S-04
- S-05
expected_attachments:
- Equipment calibration record
"""

REF_METHOD = """# TQ-7 Torque Retention Test - Method Summary

## 1 Purpose

This method verifies that the tested fasteners retain the specified torque after
the conditioning cycle. The result of each sample is a single torque value in
newton-metres read at the moment of first movement.

## 2 Apparatus

A calibrated torque wrench with a current calibration record is required. The
wrench must cover the expected range with margin, and its calibration sticker
must be checked before the first measurement of the day.

## 3 Procedure

Condition the assembled samples for 24 hours at 23 +/- 2 degrees C. Mount each
sample in the fixture and apply torque smoothly at approximately 30 seconds per
full turn. Record the torque at first movement to 0.1 Nm resolution. Measure
each sample once; do not re-measure a moved fastener.

## 4 Acceptance

The acceptance limits are defined by the protocol, not by this method document.
A sample passes when its measured torque lies inside the protocol range,
inclusive of the limits. Any result outside the range is a failure and must be
reported as measured without adjustment.
"""

REF_REPORTING = """# Reporting Guidance for Inspection Reports

## Structure

Reports in this programme follow a fixed structure: project information, test
method and reference guidance, results and evidence, then summary and
observations. Every results section must state the acceptance range and show a
per-sample Pass/Fail verdict.

## Traceability

Each measurement must be traceable to the raw data file and, where applicable,
to an equipment calibration record supplied as an attachment. Reports should
reference attachments by stable labels such as Attachment A.

## Out-of-range results

Out-of-range values must be reported exactly as measured. The report must not
rewrite, round or explain away a failed result; any investigation is documented
separately. Missing measurements must be listed as missing, never imputed.

## Draft status

Generated reports are drafts until reviewed. The draft status must remain
visible on every page of the exported package.
"""

REF_Uncertainty = """# Measurement Practice Notes (excerpt)

The resolution of the torque wrench used for TQ-7 is 0.1 Nm. Report values to
one decimal place. A single measurement is taken per sample; repeatability
studies are out of scope for this verification.

Environment: records show the conditioning room holds 23 +/- 2 degrees C for the
required 24 hour hold. Fixture slippage is the most common procedural error; if
slippage is observed, note it in the observation column of the raw data file.
"""

RESULTS_COMPLETE = """sample_id,measurement,unit,observation
S-01,48.2,Nm,steady reading
S-02,51.7,Nm,steady reading
S-03,46.9,Nm,slight settle before first movement
S-04,53.1,Nm,steady reading
S-05,49.8,Nm,steady reading
"""

RESULTS_FAILING = """sample_id,measurement,unit,observation
S-01,48.2,Nm,steady reading
S-02,58.4,Nm,reading drifted upward before movement
S-03,46.9,Nm,slight settle before first movement
S-04,53.1,Nm,steady reading
S-05,49.8,Nm,steady reading
"""

RESULTS_INCOMPLETE = """sample_id,measurement,unit,observation
S-01,48.2,Nm,steady reading
S-02,58.4,Nm,reading drifted upward before movement
S-03,46.9,Nm,slight settle before first movement
S-05,49.8,Nm,steady reading
"""


def write_docx_template(path: Path) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    for style, _lvl, text in TEMPLATE_TEXT:
        p = doc.add_paragraph(text, style=style)
        for run in p.runs:
            run.font.size = Pt(12 if style != "Title" else 20)
    doc.save(str(path))


def write_calibration_pdf(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    h = styles["Heading2"]
    body = styles["BodyText"]
    story = [
        Paragraph("Equipment Calibration Record (fictional)", styles["Title"]),
        Spacer(1, 6 * mm),
        Paragraph("Equipment: TQ-W-12 torque wrench, serial TW-88231, range 10-60 Nm", h),
        Paragraph("Calibrated by: Metrology Ltd (fictional vendor)", body),
        Paragraph("Calibration date: 2026-09-10", body),
        Paragraph("Next due: 2027-03-10", body),
        Paragraph("Result: PASS - as-found deviations within manufacturer specification.", body),
        Spacer(1, 4 * mm),
        Paragraph("Statement: This record is a synthetic sample document created for a "
                  "report-generator prototype. It is not a real calibration certificate.", body),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def write_inputs() -> None:
    import shutil

    inputs = ROOT / "inputs"
    inputs.mkdir(exist_ok=True)
    stale_refs = inputs / "references"
    if stale_refs.is_dir():
        shutil.rmtree(stale_refs)

    # Reference documents live flat next to protocol.md in every input folder.
    (inputs / "TQ-7_method_summary.md").write_text(REF_METHOD, encoding="utf-8")
    (inputs / "Reporting_guidance.md").write_text(REF_REPORTING, encoding="utf-8")
    (inputs / "Measurement_practice_notes.md").write_text(REF_Uncertainty, encoding="utf-8")

    write_docx_template(inputs / "report_template.docx")
    (inputs / "protocol.md").write_text(PROTOCOL, encoding="utf-8")
    (inputs / "results.csv").write_text(RESULTS_COMPLETE, encoding="utf-8")
    write_calibration_pdf(inputs / "equipment_calibration_record.pdf")

    # ------------------------------ demo variants ----------------------------
    fail_dir = ROOT / "inputs" / "demo_variants" / "failing"
    fail_dir.mkdir(parents=True, exist_ok=True)
    for f in inputs.iterdir():
        if f.is_file():
            shutil_copy(f, fail_dir / f.name)
    (fail_dir / "results.csv").write_text(RESULTS_FAILING, encoding="utf-8")

    inc_dir = ROOT / "inputs" / "demo_variants" / "incomplete"
    inc_dir.mkdir(parents=True, exist_ok=True)
    for f in inputs.iterdir():
        if f.is_file():
            shutil_copy(f, inc_dir / f.name)
    (inc_dir / "results.csv").write_text(RESULTS_INCOMPLETE, encoding="utf-8")
    (inc_dir / "equipment_calibration_record.pdf").unlink(missing_ok=True)

    # complete variant folder for the UI
    comp_dir = ROOT / "templates" / "demo_complete"
    comp_dir.mkdir(parents=True, exist_ok=True)
    for f in inputs.iterdir():
        if f.is_file():
            shutil_copy(f, comp_dir / f.name)
    fail_ui = ROOT / "templates" / "demo_failing"
    fail_ui.mkdir(parents=True, exist_ok=True)
    for f in inputs.iterdir():
        if f.is_file():
            shutil_copy(f, fail_ui / f.name)
    (fail_ui / "results.csv").write_text(RESULTS_FAILING, encoding="utf-8")
    inc_ui = ROOT / "templates" / "demo_incomplete"
    inc_ui.mkdir(parents=True, exist_ok=True)
    for f in inputs.iterdir():
        if f.is_file():
            shutil_copy(f, inc_ui / f.name)
    (inc_ui / "results.csv").write_text(RESULTS_INCOMPLETE, encoding="utf-8")
    (inc_ui / "equipment_calibration_record.pdf").unlink(missing_ok=True)


def shutil_copy(src: Path, dst: Path) -> None:
    import shutil

    shutil.copy2(src, dst)


if __name__ == "__main__":
    write_inputs()
    print("Inputs written to inputs/ and templates/demo_*/")
