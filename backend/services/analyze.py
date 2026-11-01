"""The analyze service (docs/DESIGN.md, Request flow for one analysis)."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

from django.conf import settings

from domain.checkpoints import choose_interval, place_checkpoints, sample_miles
from domain.constants import CORRIDOR_POINT_CAP, DISPLAY_MAX_POINTS, DISPLAY_TOLERANCE_MILES
from domain.geo import LatLon, corridor_points, grid_cell, simplify_polyline
from domain.models import WeatherSample
from domain.ranking import rank_routes
from domain.risk import assess_risk
from domain.scoring import summarize_route
from domain.weather import weather_at
from providers.interfaces import RoutingProvider, WeatherProvider

from .errors import RouteTooLongError
from .hours import HEATMAP_HOURS, floor_hour
from .results import AnalysisResult, CheckpointResult, Meta, RouteResult
from .timing import log_timings, timed

logger = logging.getLogger("routecast.analyze")

FORECAST_SOURCE = "open-meteo"


@dataclass(frozen=True)
class TripRequest:
    origin: LatLon
    destination: LatLon
    departure_utc: datetime
    load_weight_lb: int
    interval_miles: int


def analyze_trip(
    trip: TripRequest, request_id: str, routing: RoutingProvider, weather: WeatherProvider
) -> AnalysisResult:
    timings: dict[str, float] = {}
    started = perf_counter()
    try:
        return _analyze(trip, request_id, routing, weather, timings)
    finally:
        log_timings(logger, "analyze", request_id, timings, started)


def _analyze(trip, request_id, routing, weather, timings) -> AnalysisResult:
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

    placed = [
        place_checkpoints(route, interval, trip.departure_utc, truck_factor) for route in routes
    ]

    # Fetch far enough for the last ETA and for the 48-hour heatmap that follows,
    # so the heatmap request can reuse the cached series.
    latest_hour = max(
        max(cp.forecast_hour_utc for cps in placed for cp in cps),
        floor_hour(trip.departure_utc) + timedelta(hours=HEATMAP_HOURS - 1),
    )
    points = [(cp.lat, cp.lon) for cps in placed for cp in cps]
    with timed(timings, "open_meteo"):
        forecast = weather.get_series(points, latest_hour)
    if forecast.failed_cells:
        warnings.append(
            f"Weather data could not be fetched for {len(forecast.failed_cells)} location(s); "
            "their checkpoints are shown as unavailable."
        )

    route_results = []
    summaries = []
    for index, (route, checkpoints) in enumerate(zip(routes, placed)):
        scored = []
        for checkpoint in checkpoints:
            series = forecast.series.get(grid_cell(checkpoint.lat, checkpoint.lon))
            sample = weather_at(series, checkpoint.forecast_hour_utc) if series is not None else None
            scored.append(
                CheckpointResult(
                    checkpoint, sample or WeatherSample(), assess_risk(sample, trip.load_weight_lb)
                )
            )
        summary = summarize_route(
            route, index, checkpoints, [item.risk for item in scored], truck_factor
        )
        summaries.append(summary)
        route_results.append(
            RouteResult(
                route=route,
                display_geometry=tuple(
                    simplify_polyline(
                        list(route.geometry), DISPLAY_TOLERANCE_MILES, DISPLAY_MAX_POINTS
                    )
                ),
                departure_utc=trip.departure_utc,
                arrival_utc=checkpoints[-1].eta_utc,
                summary=summary,
                checkpoints=tuple(scored),
            )
        )

    recommendation = rank_routes(summaries)
    recommended = next(s for s in summaries if s.route_id == recommendation.route_id)
    if recommended.coverage_pct < 100:
        warnings.append(
            f"{recommended.label} has forecast data for {int(recommended.coverage_pct)}% of its "
            "length; the rest could not be scored."
        )

    return AnalysisResult(
        meta=Meta(
            request_id=request_id,
            interval_miles=interval,
            truck_duration_factor=truck_factor,
            forecast_source=FORECAST_SOURCE,
            warnings=tuple(warnings),
        ),
        routes=tuple(route_results),
        recommendation=recommendation,
        corridor_points=tuple(corridor_points(routes, cap=CORRIDOR_POINT_CAP)),
    )
