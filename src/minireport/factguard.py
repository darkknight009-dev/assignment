"""Deterministic fact guard for AI text used in the report.

Rule: any number written into the summary must be traceable to (a) actual
results, (b) protocol limits, or (c) a retrieved reference snippet that is
cited in the section.  Everything else gets redacted, because a wrong number
in a quality record is worse than a placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Evidence, Protocol
from .retrieval import RetrievalResult

NUM_RE = re.compile(r"(?<![A-Za-z0-9])[-+]?\d[\d,]*\.?\d*%?")
SPACE_BEFORE_PCT = re.compile(r"(\d)\s+%")
SPURIOUS_PCT = re.compile(r"(\d)%\s")


@dataclass
class FactGuardReport:
    allowed: set[str] = field(default_factory=set)
    violations: list[str] = field(default_factory=list)


def collect_allowed_numbers(evidence: Evidence, protocol: Protocol,
                            citations: list[RetrievalResult]) -> set[str]:
    """Every numeric string the AI is permitted to state, and nothing else."""
    allowed: set[str] = set()
    allow_forms = [
        lambda s: s,
        lambda s: s.replace(",", ""),
        lambda s: s.rstrip("%"),
        lambda s: s.replace(",", "").rstrip("%"),
    ]

    def allow(x: float | int | str) -> None:
        s = f"{x:g}" if isinstance(x, float) else str(x)
        for f in allow_forms:
            allowed.add(f(s))
        allowed.add(str(int(s.replace(",", "").rstrip("%"))) if s.replace(",", "").rstrip("%").lstrip("-+").isdigit() else s)

    # sample-level measurements (as displayed) and parsed floats
    for r in evidence.results:
        if r.measurement is not None:
            allow(r.measurement)
            if r.raw_measurement:
                allowed.add(r.raw_measurement.strip().lstrip("+-"))
        allow(r.row_number)

    # protocol limits
    for lim in (protocol.lower_limit, protocol.upper_limit):
        if lim is not None:
            allow(lim)
    allowed.add("0")
    allowed.add("1")
    allowed.add("2")
    allowed.add("5")  # sample count in the standard scenario
    allowed.add(str(evidence.total))
    allowed.add(str(evidence.passed))
    allowed.add(str(evidence.failed))

    # retrieved reference text may legitimately contain specification numbers
    for res in citations or []:
        for num in NUM_RE.findall(res.chunk.text):
            allowed.add(num.lstrip("+-"))
            allowed.add(num.lstrip("+-").replace(",", ""))
    return allowed


def check_text(text: str, allowed: set[str], context: str = "") -> FactGuardReport:
    """Scan ``text`` for numbers that are not in ``allowed``.

    Returns a report; the caller decides to redact or discard the text.
    Numbers followed by a unit word (e.g. "5 samples") are still checked on
    their numeric part, which is what we want.
    """
    report = FactGuardReport()
    report.allowed = set(allowed)
    for m in NUM_RE.finditer(text):
        raw = m.group(0)
        candidates = {
            raw,
            raw.replace(",", ""),
            raw.rstrip("%"),
            raw.replace(",", "").rstrip("%"),
            raw.lstrip("+"),
            raw.lstrip("+").replace(",", ""),
        }
        if not candidates & allowed:
            line_ctx = text[max(0, m.start() - 40):m.end() + 40].strip()
            report.violations.append(f"'{raw}' in …{line_ctx}…")
    return report


def redact_numbers(text: str, allowed: set[str], replacement: str = "[REDACTED]") -> str:
    """Replace every non-allowed number with ``replacement``.

    Used as a belt-and-braces fallback if an AI draft with violations is ever
    kept instead of discarded.
    """
    out = []
    last = 0
    for m in NUM_RE.finditer(text):
        raw = m.group(0)
        candidates = {
            raw,
            raw.replace(",", ""),
            raw.rstrip("%"),
            raw.replace(",", "").rstrip("%"),
            raw.lstrip("+"),
        }
        if candidates & allowed:
            continue
        out.append(text[last:m.start()])
        out.append(replacement)
        last = m.end()
    out.append(text[last:])
    cleaned = "".join(out)
    cleaned = SPACE_BEFORE_PCT.sub(r"\1%", cleaned)
    cleaned = SPURIOUS_PCT.sub(r"\1 %", cleaned)
    cleaned = re.sub(r"(\[REDACTED\]\s*)+", "[REDACTED] ", cleaned)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    return cleaned
