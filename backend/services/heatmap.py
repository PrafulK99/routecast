"""The heatmap service: risk for every corridor point at every hour of the next 48."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

from domain.geo import LatLon, grid_cell
from domain.risk import assess_risk
from domain.weather import weather_at
from providers.interfaces import WeatherProvider

from .hours import HEATMAP_HOURS, NO_FORECAST_LEVEL, floor_hour
from .results import HeatmapPoint, HeatmapResult
from .timing import log_timings, timed

logger = logging.getLogger("routecast.heatmap")


@dataclass(frozen=True)
class HeatmapRequest:
    points: tuple[LatLon, ...]
    departure_utc: datetime
    load_weight_lb: int


def heatmap_for(request: HeatmapRequest, request_id: str, weather: WeatherProvider) -> HeatmapResult:
    timings: dict[str, float] = {}
    started = perf_counter()
    try:
        start = floor_hour(request.departure_utc)
        hours = [start + timedelta(hours=h) for h in range(HEATMAP_HOURS)]
        with timed(timings, "open_meteo"):
            forecast = weather.get_series(request.points, hours[-1])

        points = []
        for lat, lon in request.points:
            series = forecast.series.get(grid_cell(lat, lon))
            levels = []
            for hour in hours:
                sample = weather_at(series, hour) if series is not None else None
                level = assess_risk(sample, request.load_weight_lb).level
                levels.append(NO_FORECAST_LEVEL if level is None else int(level))
            points.append(HeatmapPoint(lat, lon, tuple(levels)))
        return HeatmapResult(start_hour=start, hours=HEATMAP_HOURS, points=tuple(points))
    finally:
        log_timings(logger, "heatmap", request_id, timings, started)
