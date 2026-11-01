"""Cumulative distance and time, checkpoint placement, ETA and mile attribution."""

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from itertools import accumulate
from typing import Sequence

from .constants import (
    ALLOWED_INTERVALS_MILES,
    DEFAULT_TRUCK_FACTOR,
    MAX_CHECKPOINTS_PER_ROUTE,
    MILE_EPSILON,
)
from .models import Checkpoint, Route


def cumulative_totals(
    segment_miles: Sequence[float], segment_seconds: Sequence[float]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Cumulative miles and seconds at each vertex, starting with 0 at the origin."""
    if len(segment_miles) != len(segment_seconds):
        raise ValueError("segment distance and duration arrays must have equal length")
    return (
        (0.0, *accumulate(segment_miles)),
        (0.0, *accumulate(segment_seconds)),
    )


def sample_miles(total_miles: float, step_miles: float) -> list[float]:
    """Mile 0, every step, and the destination, without a duplicate at the end."""
    if total_miles <= 0 or step_miles <= 0:
        raise ValueError("total_miles and step_miles must be positive")
    miles = [0.0]
    k = 1
    while k * step_miles < total_miles - MILE_EPSILON:
        miles.append(k * step_miles)
        k += 1
    miles.append(total_miles)
    return miles


def choose_interval(
    total_miles: float, requested: int, max_checkpoints: int = MAX_CHECKPOINTS_PER_ROUTE
) -> int:
    """The requested interval, or the next larger allowed one when it would give
    more than `max_checkpoints`. The caller reports a change, and checks whether
    even the largest interval is still too many (it is returned in that case)."""
    if requested not in ALLOWED_INTERVALS_MILES:
        raise ValueError(f"interval must be one of {ALLOWED_INTERVALS_MILES}, got {requested!r}")
    larger = [i for i in ALLOWED_INTERVALS_MILES if i >= requested]
    for interval in larger:
        if len(sample_miles(total_miles, interval)) <= max_checkpoints:
            return interval
    return larger[-1]


def interpolate_at_mile(route: Route, mile: float) -> tuple[float, float, float]:
    """(lat, lon, elapsed seconds) at a mile marker, by linear interpolation
    between the two surrounding vertices."""
    cum_mi = route.cumulative_mi
    mile = min(max(mile, 0.0), cum_mi[-1])
    i = min(max(bisect_right(cum_mi, mile) - 1, 0), len(cum_mi) - 2)
    span = cum_mi[i + 1] - cum_mi[i]
    t = (mile - cum_mi[i]) / span if span > 0 else 0.0
    (lat0, lon0), (lat1, lon1) = route.geometry[i], route.geometry[i + 1]
    return (
        lat0 + (lat1 - lat0) * t,
        lon0 + (lon1 - lon0) * t,
        route.cumulative_s[i] + (route.cumulative_s[i + 1] - route.cumulative_s[i]) * t,
    )


def _require_aware(value: datetime, name: str) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def eta(departure: datetime, elapsed_s: float, truck_factor: float = DEFAULT_TRUCK_FACTOR) -> datetime:
    """Departure plus routing seconds times the truck factor, in UTC."""
    return _require_aware(departure, "departure") + timedelta(seconds=elapsed_s * truck_factor)


def forecast_hour(eta_utc: datetime) -> datetime:
    """The ETA rounded to the nearest whole UTC hour; half rounds up."""
    shifted = _require_aware(eta_utc, "eta") + timedelta(minutes=30)
    return shifted.replace(minute=0, second=0, microsecond=0)


def segment_miles(miles: Sequence[float], total_miles: float) -> list[float]:
    """The stretch each checkpoint owns: halfway to its neighbours on each side.
    The first starts at mile 0 and the last ends at the destination."""
    last = len(miles) - 1
    result = []
    for i, mile in enumerate(miles):
        start = 0.0 if i == 0 else (miles[i - 1] + mile) / 2
        end = total_miles if i == last else (mile + miles[i + 1]) / 2
        result.append(end - start)
    return result


def place_checkpoints(
    route: Route,
    interval_miles: int,
    departure: datetime,
    truck_factor: float = DEFAULT_TRUCK_FACTOR,
) -> list[Checkpoint]:
    miles = sample_miles(route.distance_mi, interval_miles)
    segments = segment_miles(miles, route.distance_mi)
    checkpoints = []
    for index, (mile, segment) in enumerate(zip(miles, segments)):
        lat, lon, elapsed_s = interpolate_at_mile(route, mile)
        eta_utc = eta(departure, elapsed_s, truck_factor)
        checkpoints.append(
            Checkpoint(
                index=index,
                mile=mile,
                lat=lat,
                lon=lon,
                eta_utc=eta_utc,
                forecast_hour_utc=forecast_hour(eta_utc),
                segment_mi=segment,
            )
        )
    return checkpoints
