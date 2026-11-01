"""What the services return. They hold domain objects; the API serializers shape them."""

from dataclasses import dataclass
from datetime import datetime

from domain.geo import LatLon
from domain.models import Checkpoint, Recommendation, RiskResult, Route, RouteSummary, WeatherSample


@dataclass(frozen=True)
class CheckpointResult:
    checkpoint: Checkpoint
    weather: WeatherSample  # every value None when no forecast covers the checkpoint
    risk: RiskResult


@dataclass(frozen=True)
class RouteResult:
    route: Route
    display_geometry: tuple[LatLon, ...]  # simplified; the full geometry stays server side
    departure_utc: datetime
    arrival_utc: datetime
    summary: RouteSummary
    checkpoints: tuple[CheckpointResult, ...]


@dataclass(frozen=True)
class Meta:
    request_id: str
    interval_miles: int
    truck_duration_factor: float
    forecast_source: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisResult:
    meta: Meta
    routes: tuple[RouteResult, ...]
    recommendation: Recommendation
    corridor_points: tuple[LatLon, ...]


@dataclass(frozen=True)
class HeatmapPoint:
    lat: float
    lon: float
    levels: tuple[int, ...]  # one per hour, -1 where there is no forecast


@dataclass(frozen=True)
class HeatmapResult:
    start_hour: datetime
    hours: int
    points: tuple[HeatmapPoint, ...]
