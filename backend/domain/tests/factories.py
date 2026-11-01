"""Small builders shared by the domain tests."""

from datetime import datetime, timezone

from domain.checkpoints import cumulative_totals
from domain.constants import Level
from domain.models import Route, RouteSummary

DEPARTURE = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def straight_route(total_miles, seconds_per_mile=60.0, route_id="r", label="Route A", vertices=2):
    """A route along the equator (lon grows, lat 0) with equal-length segments."""
    segments = vertices - 1
    segment_mi = [total_miles / segments] * segments
    segment_s = [total_miles / segments * seconds_per_mile] * segments
    cum_mi, cum_s = cumulative_totals(segment_mi, segment_s)
    geometry = tuple((0.0, mile / 69.0) for mile in cum_mi)
    return Route(route_id, label, geometry, cum_mi, cum_s)


def summary(
    label="Route A",
    index=0,
    no_travel=0.0,
    severe=0.0,
    high=0.0,
    avg_risk=0.5,
    duration_s=3600.0,
    distance_mi=100.0,
    coverage_pct=100.0,
):
    miles = {level: 0.0 for level in Level}
    miles[Level.NO_TRAVEL], miles[Level.SEVERE], miles[Level.HIGH] = no_travel, severe, high
    return RouteSummary(
        route_id=label,
        label=label,
        route_index=index,
        distance_mi=distance_mi,
        duration_s=duration_s,
        miles_by_level=miles,
        avg_risk=avg_risk,
        worst_level=None if avg_risk is None else Level.LOW,
        coverage_pct=coverage_pct,
        blocked=no_travel > 0,
    )
