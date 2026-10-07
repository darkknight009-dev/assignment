"""Input bundle: locate and load every input file into typed objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import Protocol
from .parsers import parse_protocol, parse_results_csv

# Filenames we look for, in priority order.  Keeps the UI simple: point the
# app at a folder (or upload files) and it sorts itself out.
PROTOCOL_NAMES = ("protocol.md", "protocol.txt")
RESULTS_NAMES = ("results.csv",)
TEMPLATE_NAMES = ("report_template.docx",)


@dataclass
class InputBundle:
    """All loaded inputs plus helper views used by the generators."""

    directory: Path
    protocol: Protocol
    results_csv_path: Path
    template_path: Path
    references: list[Path] = field(default_factory=list)
    attachments: list[Path] = field(default_factory=list)

    # extras discovered in the input folder (surfaced in the UI)
    unexpected_files: list[str] = field(default_factory=list)

    @property
    def reference_paths(self) -> list[Path]:
        return self.references

    @property
    def attachment_paths(self) -> list[Path]:
        return self.attachments

    def missing_expected_attachments(self) -> list[str]:
        """Expected attachment names from the protocol that were not supplied.

        Matching is case-insensitive and ignores the file extension, so a
        protocol entry like "Equipment calibration record" matches the file
        ``equipment_calibration_record.pdf``.
        """

        def norm(name: str) -> str:
            n = name.lower()
            if n.endswith(".pdf") or n.endswith(".docx") or n.endswith(".csv"):
                n = n.rsplit(".", 1)[0]
            return re.sub(r"[^a-z0-9]+", " ", n).strip()

        supplied = {norm(p.name) for p in self.attachments}
        missing = []
        for name in self.protocol.expected_attachments:
            if norm(name) not in supplied:
                missing.append(name)
        return missing


def _first_existing(folder: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def load_inputs(directory: str | Path) -> InputBundle:
    """Load all inputs from ``directory`` and raise on hard-missing files."""
    folder = Path(directory)
    protocol_path = _first_existing(folder, PROTOCOL_NAMES)
    results_path = _first_existing(folder, RESULTS_NAMES)
    template_path = _first_existing(folder, TEMPLATE_NAMES)

    problems = []
    if protocol_path is None:
        problems.append(f"protocol file not found in {folder} (expected one of {PROTOCOL_NAMES})")
    if results_path is None:
        problems.append(f"results CSV not found in {folder} (expected {RESULTS_NAMES})")
    if template_path is None:
        problems.append(f"report template not found in {folder} (expected {TEMPLATE_NAMES})")
    if problems:
        raise FileNotFoundError("; ".join(problems))

    protocol = parse_protocol(protocol_path)
    references = sorted(
        [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".md", ".txt"} and p.name not in PROTOCOL_NAMES],
        key=lambda p: p.name.lower(),
    )
    attachments = sorted(
        [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith("~$")],
        key=lambda p: p.name.lower(),
    )
    known = set(PROTOCOL_NAMES) | set(RESULTS_NAMES) | set(TEMPLATE_NAMES)
    unexpected = sorted(
        p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith("~$") and p.name not in known and p.suffix.lower() not in {".md", ".txt", ".pdf"}
    )

    return InputBundle(
        directory=folder,
        protocol=protocol,
        results_csv_path=results_path,
        template_path=template_path,
        references=references,
        attachments=attachments,
        unexpected_files=unexpected,
    )
