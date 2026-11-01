"""Per-route metrics from scored checkpoints (docs/DESIGN.md, Per-route metrics)."""

from typing import Sequence

from .constants import DEFAULT_TRUCK_FACTOR, Level
from .models import Checkpoint, RiskResult, Route, RouteSummary


def summarize_route(
    route: Route,
    route_index: int,
    checkpoints: Sequence[Checkpoint],
    risks: Sequence[RiskResult],
    truck_factor: float = DEFAULT_TRUCK_FACTOR,
) -> RouteSummary:
    """Miles at each level, average risk, duration, coverage and blocked flag.

    A checkpoint without a level is excluded from the mile totals and the
    average, and lowers coverage. Miles stay unrounded here; ranking rounds them.
    """
    if len(checkpoints) != len(risks):
        raise ValueError("need exactly one risk result per checkpoint")

    miles_by_level = {level: 0.0 for level in Level}
    for checkpoint, risk in zip(checkpoints, risks):
        if risk.level is not None:
            miles_by_level[risk.level] += checkpoint.segment_mi

    scored_miles = sum(miles_by_level.values())
    avg_risk = (
        sum(level * miles for level, miles in miles_by_level.items()) / scored_miles
        if scored_miles > 0
        else None
    )
    levels = [risk.level for risk in risks if risk.level is not None]
    return RouteSummary(
        route_id=route.id,
        label=route.label,
        route_index=route_index,
        distance_mi=route.distance_mi,
        duration_s=route.duration_s * truck_factor,
        miles_by_level=miles_by_level,
        avg_risk=avg_risk,
        worst_level=max(levels) if levels else None,
        coverage_pct=min(100.0, scored_miles / route.distance_mi * 100),
        blocked=miles_by_level[Level.NO_TRAVEL] > 0,
    )
