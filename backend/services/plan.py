"""The plan service: which weather an analysis needs, without fetching any.

The browser asks first, fetches Open-Meteo itself, then sends the weather back with the
analyze request (docs/DESIGN.md, Request flow for one analysis). The routing step is shared
with the analyze service, and Mapbox answers are cached, so analyze repeats no routing calls.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

from django.conf import settings

from domain.checkpoints import choose_interval, place_checkpoints, sample_miles
from domain.geo import LatLon, grid_cell
from domain.models import Checkpoint, Route
from providers.interfaces import RoutingProvider

from .errors import RouteTooLongError
from .hours import HEATMAP_HOURS, floor_hour
from .timing import log_timings, timed

logger = logging.getLogger("routecast.plan")


@dataclass(frozen=True)
class PlannedTrip:
    """Routes with their checkpoints placed, and the forecast hours they need."""

    routes: list[Route]
    warnings: list[str]
    interval_miles: int
    placed: list[list[Checkpoint]]
    latest_hour: datetime  # the last ETA hour, or 48 hours after departure if that is later


@dataclass(frozen=True)
class WeatherPlan:
    cells: tuple[LatLon, ...]  # unique grid cells of every checkpoint of every route, first seen first
    first_hour: datetime
    last_hour: datetime


def plan_routes(trip, routing: RoutingProvider, timings: dict[str, float]) -> PlannedTrip:
    """Routes, interval and checkpoints for a trip (steps 3 and 4 of the request flow)."""
    truck_factor = settings.TRUCK_DURATION_FACTOR
    max_checkpoints = settings.MAX_CHECKPOINTS_PER_ROUTE

    with timed(timings, "mapbox"):
        routing_result = routing.get_routes(trip.origin, trip.destination)
    routes = list(routing_result.routes)
    warnings = list(routing_result.warnings)

    # The longest route needs the most checkpoints, so it decides the interval.
    longest = max(route.distance_mi for route in routes)
    interval = choose_interval(longest, trip.interval_miles, max_checkpoints)
    if len(sample_miles(longest, interval)) > max_checkpoints:
        raise RouteTooLongError(
            f"The longest route is {longest:.0f} miles, which needs more than "
            f"{max_checkpoints} checkpoints even at {interval}-mile spacing."
        )
    if interval != trip.interval_miles:
        warnings.append(
            f"Checkpoint interval raised from {trip.interval_miles} to {interval} miles "
            f"so each route stays within {max_checkpoints} checkpoints."
        )

    placed = [place_checkpoints(route, interval, trip.departure_utc, truck_factor) for route in routes]

    # Fetch far enough for the last ETA and for the 48-hour heatmap that follows,
    # so the heatmap request can reuse the same series.
    latest_hour = max(
        max(cp.forecast_hour_utc for cps in placed for cp in cps),
        floor_hour(trip.departure_utc) + timedelta(hours=HEATMAP_HOURS - 1),
    )
    return PlannedTrip(routes, warnings, interval, placed, latest_hour)


def plan_weather(trip, request_id: str, routing: RoutingProvider) -> WeatherPlan:
    timings: dict[str, float] = {}
    started = perf_counter()
    try:
        planned = plan_routes(trip, routing, timings)
        cells = dict.fromkeys(
            grid_cell(cp.lat, cp.lon) for checkpoints in planned.placed for cp in checkpoints
        )
        first_hour = min(cp.forecast_hour_utc for checkpoints in planned.placed for cp in checkpoints)
        return WeatherPlan(tuple(cells), first_hour, planned.latest_hour)
    finally:
        log_timings(logger, "plan", request_id, timings, started)
