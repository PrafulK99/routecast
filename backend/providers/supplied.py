"""Weather handed to us with the request (fetched by the browser) behind the WeatherProvider interface."""

from datetime import datetime
from typing import Iterable, Mapping

from domain.geo import grid_cell

from .errors import WeatherUnavailableError
from .interfaces import Cell, LatLon, Series, WeatherResult


class SuppliedWeatherProvider:
    """Serves the cells it was given. A cell it was not given comes back in failed_cells, so its
    checkpoints become unavailable with a warning, never Low. It has no cache and never writes to
    one: data a client sent must not be served to anyone else."""

    def __init__(self, series: Mapping[Cell, Series]):
        self._series = series

    def get_series(self, points: Iterable[LatLon], latest_hour: datetime) -> WeatherResult:
        cells = list(dict.fromkeys(grid_cell(lat, lon) for lat, lon in points))
        found = {cell: self._series[cell] for cell in cells if cell in self._series}
        missing = frozenset(cell for cell in cells if cell not in self._series)
        if missing and not found:
            raise WeatherUnavailableError("No weather was supplied for any location on these routes.")
        return WeatherResult(found, missing)
