"""What the service layer depends on. Adapters and fakes both satisfy these."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Protocol

from domain.geo import LatLon
from domain.models import Route, WeatherSample

Cell = LatLon  # a grid cell is the rounded (lat, lon)
Series = Mapping[datetime, WeatherSample]

WARNING_MISSING_ANNOTATIONS = (
    "Mapbox returned no usable per-segment data, so travel times are spread evenly by distance."
)
WARNING_ROUTE_FALLBACK = "Fewer than three routes came back, so extra routes were found via waypoints."


def warning_few_routes(count: int) -> str:
    return f"Only {count} route{'s' if count != 1 else ''} could be found."


class Cache(Protocol):
    """Django's cache satisfies this, so providers never import Django."""

    def get(self, key: str) -> Any: ...

    def set(self, key: str, value: Any, timeout: float) -> None: ...


@dataclass(frozen=True)
class RoutingResult:
    routes: tuple[Route, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class WeatherResult:
    """series maps each grid cell (domain.geo.grid_cell) to its hourly samples;
    failed_cells could not be fetched and must become unavailable checkpoints."""

    series: Mapping[Cell, Series]
    failed_cells: frozenset[Cell] = frozenset()


class RoutingProvider(Protocol):
    def get_routes(self, origin: LatLon, destination: LatLon) -> RoutingResult:
        """Up to three routes. Raises NoRouteError or RoutingUnavailableError."""


class WeatherProvider(Protocol):
    def get_series(self, points: Iterable[LatLon], latest_hour: datetime) -> WeatherResult:
        """Hourly samples for the grid cells of `points`, covering `latest_hour`.
        Raises WeatherRateLimitedError, or WeatherUnavailableError if every cell failed."""
