"""Typed per-request objects (docs/DESIGN.md, Data model). Never saved."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping

from .constants import Level

Status = Literal["ok", "partial", "unavailable"]
Factor = Literal["wind", "rain", "snow"]


@dataclass(frozen=True)
class WeatherSample:
    """Forecast values for one checkpoint. A missing value is None, never 0."""

    wind_mph: float | None = None
    rain_in_hr: float | None = None
    snow_in_hr: float | None = None


@dataclass(frozen=True)
class RiskResult:
    """Output of the risk function. level is None when status is unavailable."""

    level: Level | None
    wind_level: Level | None
    rain_level: Level | None
    snow_level: Level | None
    factor: Factor | None
    load_rule_applied: bool
    status: Status


@dataclass(frozen=True)
class Route:
    """A route with cumulative miles and seconds at every geometry vertex.

    geometry holds (lat, lon) pairs. Durations are the routing provider's, before
    the truck factor.
    """

    id: str
    label: str
    geometry: tuple[tuple[float, float], ...]
    cumulative_mi: tuple[float, ...]
    cumulative_s: tuple[float, ...]

    def __post_init__(self):
        if len(self.geometry) < 2:
            raise ValueError("a route needs at least two vertices")
        if not len(self.geometry) == len(self.cumulative_mi) == len(self.cumulative_s):
            raise ValueError("geometry and cumulative arrays must have equal length")

    @property
    def distance_mi(self) -> float:
        return self.cumulative_mi[-1]

    @property
    def duration_s(self) -> float:
        return self.cumulative_s[-1]


@dataclass(frozen=True)
class Checkpoint:
    index: int
    mile: float
    lat: float
    lon: float
    eta_utc: datetime
    forecast_hour_utc: datetime
    segment_mi: float


@dataclass(frozen=True)
class RouteSummary:
    """Per-route metrics, the input to ranking. duration_s is truck-adjusted.

    avg_risk and worst_level are None when no checkpoint could be scored.
    """

    route_id: str
    label: str
    route_index: int
    distance_mi: float
    duration_s: float
    miles_by_level: Mapping[Level, float]
    avg_risk: float | None
    worst_level: Level | None
    coverage_pct: float
    blocked: bool


@dataclass(frozen=True)
class RankingEntry:
    """sort_key is (No Travel mi, Severe mi, High mi, average risk, duration_s) as ranked."""

    rank: int
    route_id: str
    sort_key: tuple[float, float, float, float | None, float]


@dataclass(frozen=True)
class Recommendation:
    route_id: str
    reasons: tuple[str, ...]
    all_blocked: bool
    ranking: tuple[RankingEntry, ...]
