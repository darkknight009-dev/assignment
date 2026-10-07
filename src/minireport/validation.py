"""Validation checklist: planned vs actual, missing inputs, limits, template."""

from __future__ import annotations

from .evidence import missing_measurement_ids, out_of_range_ids
from .inputs import InputBundle
from .models import DRAFT_BANNER, WarningItem


def build_checklist(
    bundle: InputBundle,
    evidence,
    unfilled_placeholders: list[str] | None = None,
) -> list[WarningItem]:
    """Build the validation checklist required by the assignment:

    * planned vs actual sample count and sample IDs
    * missing measurements or required attachments
    * results outside the supplied acceptance range
    * unfilled template placeholders
    """
    items: list[WarningItem] = []
    proto = bundle.protocol

    # 1. planned vs actual ----------------------------------------------------
    planned_ids = proto.planned_sample_ids
    actual_ids = [r.sample_id for r in evidence.results]
    planned_set, actual_set = set(planned_ids), set(actual_ids)
    extra = [s for s in actual_ids if s not in planned_set]
    missing = [s for s in planned_ids if s not in actual_set]

    if not planned_ids:
        items.append(WarningItem("PLANNED_SAMPLES_MISSING", "error",
                                 "Protocol lists no planned samples; cannot cross-check plan vs actual."))
    if extra:
        items.append(WarningItem("UNPLANNED_SAMPLES", "error",
                                 f"CSV contains {len(extra)} sample ID(s) not in the protocol plan: {', '.join(extra)}"))
    if missing:
        items.append(WarningItem("MISSING_SAMPLES", "error",
                                 f"Planned sample(s) missing from results CSV: {', '.join(missing)} "
                                 f"(planned {len(planned_ids)}, received {len(actual_ids)})."))
    if not extra and not missing and planned_ids and len(planned_ids) == len(actual_ids):
        items.append(WarningItem("SAMPLES_MATCH", "info",
                                 f"All {len(planned_ids)} planned samples present in the results CSV."))

    # 2. missing measurements / attachments ----------------------------------
    miss_meas = missing_measurement_ids(evidence)
    if miss_meas:
        items.append(WarningItem("MISSING_MEASUREMENTS", "error",
                                 f"Missing measurement for: {', '.join(miss_meas)}"))
    missing_att = bundle.missing_expected_attachments()
    for name in missing_att:
        items.append(WarningItem("MISSING_ATTACHMENT", "error",
                                 f"Expected attachment not supplied: {name}"))
    supplied_atts = ", ".join(p.name for p in bundle.attachments) or "(none)"
    if bundle.attachments:
        items.append(WarningItem("ATTACHMENTS_SUPPLIED", "info",
                                 f"{len(bundle.attachments)} attachment(s) supplied: {supplied_atts}"))
    if not miss_meas and not missing_att:
        items.append(input_group_ok(bundle, evidence))

    # 3. out-of-range results --------------------------------------------------
    oor = out_of_range_ids(evidence)
    if oor:
        items.append(WarningItem("OUT_OF_RANGE", "error",
                                 f"{len(oor)} result(s) outside acceptance range [{_lim(proto.lower_limit)}, {_lim(proto.upper_limit)}] "
                                 f"{proto.units}: {', '.join(oor)}. Out-of-range values are reported as-is; "
                                 "they are never rewritten or removed."))
    else:
        items.append(WarningItem("RANGE_OK", "info",
                                 f"All {evidence.total} measured samples within acceptance range "
                                 f"[{_lim(proto.lower_limit)}, {_lim(proto.upper_limit)}] {proto.units}."))

    # 4. template placeholders -------------------------------------------------
    if unfilled_placeholders:
        items.append(WarningItem("UNFILLED_PLACEHOLDERS", "warning",
                                 f"Template placeholders left unfilled: {', '.join(sorted(set(unfilled_placeholders)))}"))
    else:
        items.append(filled_ok(unfilled_placeholders))

    return items


def input_group_ok(bundle: InputBundle, evidence) -> WarningItem:
    miss_meas = missing_measurement_ids(evidence)
    missing_att = bundle.missing_expected_attachments()
    parts = []
    if not miss_meas and not missing_att:
        parts.append("all measurements present")
        parts.append(f"all expected attachments supplied ({', '.join(p.name for p in bundle.attachments)})")
    else:
        if miss_meas:
            parts.append(f"missing measurements: {', '.join(miss_meas)}")
        if missing_att:
            parts.append(f"missing attachments: {', '.join(missing_att)}")
    return WarningItem("INPUTS_CHECKED", "info", f"Input completeness: {'; '.join(parts)}.")


def filled_ok(unfilled):
    return WarningItem("PLACEHOLDERS_FILLED", "info",
                       "All template placeholders filled." if not unfilled else "Placeholder check complete.")


def _lim(v: float | None) -> str:
    return "open" if v is None else f"{v:g}"


def has_blocking_errors(items: list[WarningItem]) -> bool:
    return any(i.severity == "error" for i in items)


def draft_banner() -> str:
    return DRAFT_BANNER
