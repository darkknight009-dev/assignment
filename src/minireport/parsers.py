"""Parsers for the structured inputs: protocol, raw CSV results, template."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Protocol, SampleResult

PLACEHOLDER_PATTERN = re.compile(r"\[\[\s*([A-Za-z0-9_]+)\s*\]\]")


# ---------------------------------------------------------------- protocol --
def parse_protocol(path: str | Path) -> Protocol:
    """Parse the markdown protocol file.

    Keys are written as ``key: value``; lists use repeated ``- item`` lines
    under ``planned_samples`` / ``expected_attachments``.  Unknown keys are
    ignored so the format stays forward compatible.
    """
    p = Path(path)
    proto = Protocol(source_path=str(p))
    current_list: str | None = None

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            item = line[2:].strip()
            if current_list == "samples":
                proto.planned_sample_ids.append(item)
            elif current_list == "attachments":
                proto.expected_attachments.append(item)
            continue

        m = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip()
        current_list = None

        if key == "protocol_id":
            proto.protocol_id = value
        elif key == "title":
            proto.title = value
        elif key == "component":
            proto.component = value
        elif key == "revision":
            proto.revision = value
        elif key == "date":
            proto.date = value
        elif key == "test_method":
            proto.test_method = value
        elif key == "unit":
            proto.units = value
        elif key == "lower_limit":
            proto.lower_limit = _to_float(value)
        elif key == "upper_limit":
            proto.upper_limit = _to_float(value)
        elif key == "criteria":
            proto.criteria_text = value
        elif key == "planned_samples":
            proto.planned_sample_ids = [v.strip() for v in value.split(",") if v.strip()]
            current_list = "samples"
        elif key == "expected_attachments":
            proto.expected_attachments = [v.strip() for v in value.split(",") if v.strip()]
            current_list = "attachments"
    return proto


def _to_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


# ------------------------------------------------------------------- csv ----
def parse_results_csv(path: str | Path) -> list[SampleResult]:
    """Read the raw results CSV: sample_id, measurement, unit, observation.

    ``row_number`` records the 1-based CSV data row (header excluded) so the
    report and Excel files can cite "results.csv row 3" as provenance.
    """
    results: list[SampleResult] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            raw = (row.get("measurement") or "").strip()
            results.append(
                SampleResult(
                    sample_id=(row.get("sample_id") or "").strip(),
                    measurement=_to_float(raw),
                    unit=(row.get("unit") or "").strip(),
                    observation=(row.get("observation") or "").strip(),
                    raw_measurement=raw,
                    row_number=i,
                )
            )
    return results


# --------------------------------------------------------------- template ---
def parse_template_sections(docx_path: str | Path) -> list[tuple[str, list, list]]:
    """Split template document into (heading_text, body_paras, table_defs).

    Body paragraphs keep their full XML tree so runs, bolding and list
    numbering survive when we copy them into the generated report.
    """
    from docx import Document

    doc = Document(str(docx_path))
    blocks: list[tuple[str, list, list]] = []
    current: str | None = None
    body: list = []
    tables: list = []

    for para in doc.paragraphs:
        style = para.style.name if para.style is not None else ""
        if style.startswith("Heading") and para.text.strip():
            if current is not None:
                blocks.append((current, body, tables))
            current = para.text.strip()
            body, tables = [], []
        elif current is not None:
            body.append(para)
    if current is not None:
        blocks.append((current, body, tables))
    return blocks
