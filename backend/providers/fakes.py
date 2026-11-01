"""Test doubles for the provider interfaces. No network, no Django."""

from datetime import datetime
from typing import Any, Iterable, Mapping

from domain.geo import grid_cell

from .errors import ProviderError
from .interfaces import Cell, LatLon, RoutingResult, Series, WeatherResult


class InMemoryCache:
    """A dict satisfying the Cache protocol. Timeouts are recorded, not enforced."""

    def __init__(self):
        self.values: dict[str, Any] = {}
        self.timeouts: dict[str, float] = {}

    def get(self, key: str) -> Any:
        return self.values.get(key)

    def set(self, key: str, value: Any, timeout: float) -> None:
        self.values[key] = value
        self.timeouts[key] = timeout


class FakeRoutingProvider:
    """Returns a fixed RoutingResult, or raises `error` (a ProviderError)."""

    def __init__(self, result: RoutingResult | None = None, error: ProviderError | None = None):
        self._result = result
        self._error = error
        self.calls: list[tuple[LatLon, LatLon]] = []

    def get_routes(self, origin: LatLon, destination: LatLon) -> RoutingResult:
        self.calls.append((origin, destination))
        if self._error is not None:
            raise self._error
        return self._result


class FakeWeatherProvider:
    """Serves hourly samples from a dict keyed by grid cell. Cells it has no
    data for come back in failed_cells, like a partial provider failure."""

    def __init__(
        self,
        series: Mapping[Cell, Series] | None = None,
        error: ProviderError | None = None,
    ):
        self._series = dict(series or {})
        self._error = error
        self.calls: list[tuple[list[LatLon], datetime]] = []

    def get_series(self, points: Iterable[LatLon], latest_hour: datetime) -> WeatherResult:
        points = list(points)
        self.calls.append((points, latest_hour))
        if self._error is not None:
            raise self._error
        cells = list(dict.fromkeys(grid_cell(lat, lon) for lat, lon in points))
        return WeatherResult(
            {cell: self._series[cell] for cell in cells if cell in self._series},
            frozenset(cell for cell in cells if cell not in self._series),
        )
