"""Deterministic evidence: compare actual results against protocol limits.

This module is the ONLY place in the codebase where a Pass/Fail decision is
computed.  The report, the Excel attachment, the combined PDF and the AI
narrative all read from the :class:`Evidence` produced here, which guarantees
consistent numbers across every artifact.
"""

from __future__ import annotations

from .models import Evidence, Protocol, SampleResult


def _in_range(value: float, low: float | None, high: float | None) -> bool:
    """Inclusive acceptance range; open-ended when a limit is missing."""
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def build_evidence(results: list[SampleResult], protocol: Protocol) -> Evidence:
    """Evaluate each result against the protocol acceptance range.

    Evaluation entries carry every field the renderers need, including the
    exact limit values used, so nothing downstream has to re-derive them.
    """
    ev = Evidence(results=results)
    ev.total = len(results)
    for r in results:
        if r.measurement is None:
            verdict, detail = "NO DATA", "measurement missing in CSV"
        else:
            ok = _in_range(r.measurement, protocol.lower_limit, protocol.upper_limit)
            verdict = "Pass" if ok else "Fail"
            if ok:
                detail = f"{r.measurement:g} within [{_fmt(protocol.lower_limit)}, {_fmt(protocol.upper_limit)}]"
            else:
                low = "" if protocol.lower_limit is None else f"{protocol.lower_limit:g}"
                high = "" if protocol.upper_limit is None else f"{protocol.upper_limit:g}"
                detail = f"{r.measurement:g} outside [{low}, {high}]"
        ev.evaluations.append(
            {
                "sample_id": r.sample_id,
                "measurement": r.measurement,
                "measurement_display": r.measurement_display,
                "unit": r.unit,
                "observation": r.observation,
                "row_number": r.row_number,
                "verdict": verdict,
                "detail": detail,
            }
        )
        if verdict == "Pass":
            ev.passed += 1
        elif verdict == "Fail":
            ev.failed += 1
    return ev


def _fmt(v: float | None) -> str:
    return "open" if v is None else f"{v:g}"


def out_of_range_ids(evidence: Evidence) -> list[str]:
    return [e["sample_id"] for e in evidence.evaluations if e["verdict"] == "Fail"]


def missing_measurement_ids(evidence: Evidence) -> list[str]:
    return [e["sample_id"] for e in evidence.evaluations if e["verdict"] == "NO DATA"]
