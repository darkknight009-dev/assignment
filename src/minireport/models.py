"""Core data models shared by every stage of the generator.

Design note: a single :class:`Evidence` object is produced once from the raw
inputs and then consumed by the report builder, the Excel builder, the PDF
assembler and the validation module.  All numeric Pass/Fail decisions are made
exactly once, inside :mod:`minireport.evidence`, which is why every generated
artifact shows the same values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

DRAFT_BANNER = "Draft - Requires Review"


@dataclass
class Protocol:
    """Structured view of the sample protocol (planning document)."""

    protocol_id: str = ""
    title: str = ""
    component: str = ""
    revision: str = ""
    date: str = ""
    test_method: str = ""
    units: str = ""
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None
    planned_sample_ids: list[str] = field(default_factory=list)
    expected_attachments: list[str] = field(default_factory=list)
    criteria_text: str = ""
    source_path: str = ""


@dataclass
class SampleResult:
    """One row of the raw CSV results file."""

    sample_id: str = ""
    measurement: Optional[float] = None
    unit: str = ""
    observation: str = ""
    raw_measurement: str = ""
    row_number: int = 0  # CSV line number, used for provenance references

    @property
    def measurement_display(self) -> str:
        if self.measurement is None:
            return "MISSING"
        return self.raw_measurement or f"{self.measurement:g}"


@dataclass
class Evidence:
    """Deterministic evaluation of actual results against protocol limits."""

    results: list[SampleResult] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0

    def evaluation_for(self, sample_id: str) -> Optional[dict[str, Any]]:
        for ev in self.evaluations:
            if ev["sample_id"] == sample_id:
                return ev
        return None


@dataclass
class WarningItem:
    """A single validation warning / checklist finding."""

    code: str
    severity: str  # "error" | "warning" | "info"
    message: str
    details: str = ""


@dataclass
class Citation:
    """Provenance for one retrieved chunk of a reference document."""

    source: str  # file name
    reference: str  # e.g. "Method_Guide.docx p2 para2"
    text: str
    score: float = 0.0


@dataclass
class SectionContent:
    """Generated content for one report section plus its provenance."""

    key: str  # section key matching template heading
    process: str  # deterministic | rag | evidence | ai
    body: str  # final text placed into the report
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_used: bool = False
    ai_discarded: bool = False  # AI draft was generated but failed fact check
    ai_discard_reason: str = ""
    ai_model: str = ""  # which model produced the kept/discarded draft
    ai_attempts: list = field(default_factory=list)  # [(model, "ok"|"error: ...")] from fallback chain
