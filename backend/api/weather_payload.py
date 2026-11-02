"""The optional `weather` field of /api/analyze and /api/heatmap: weather the browser fetched itself.

Entries mirror Open-Meteo's hourly output in the units we request (mph, inches). The field is
untrusted: it is checked strictly, and it is used for weather values only. A cell is found by
the server's own grid_cell of the entry's lat and lon; every other fact about the trip comes
from the server's own routing.
"""

import math
import re
from datetime import datetime

from django.conf import settings
from rest_framework import serializers

from domain.geo import grid_cell
from providers.constants import MAX_ROUTES
from providers.openmeteo import parse_forecast

MAX_WEATHER_HOURS = 400
ARRAYS = ("wind_speed_10m", "rain", "showers", "snowfall")
KEYS = frozenset(("lat", "lon", "time", *ARRAYS))
HOUR = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:00")  # UTC, on the hour, no zone suffix: Open-Meteo's GMT output


def max_cells() -> int:
    """Every cell of 3 routes of the most checkpoints a route may have."""
    return MAX_ROUTES * settings.MAX_CHECKPOINTS_PER_ROUTE


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_times(where: str, times) -> None:
    if not isinstance(times, list) or not 1 <= len(times) <= MAX_WEATHER_HOURS:
        raise serializers.ValidationError(f"{where}.time must be a list of 1 to {MAX_WEATHER_HOURS} hours.")
    previous = ""
    for index, text in enumerate(times):
        if not isinstance(text, str) or not HOUR.fullmatch(text):
            raise serializers.ValidationError(
                f"{where}.time[{index}] must be a UTC hour such as 2026-11-02T14:00, with no zone suffix."
            )
        try:
            datetime.fromisoformat(text)
        except ValueError:
            raise serializers.ValidationError(f"{where}.time[{index}] is not a real date and time.") from None
        if text <= previous:  # the fixed format sorts the same as time does
            raise serializers.ValidationError(f"{where}.time must be in strictly increasing order.")
        previous = text


def _check_values(where: str, name: str, values, hours: int) -> None:
    if not isinstance(values, list) or len(values) != hours:
        raise serializers.ValidationError(f"{where}.{name} must be a list with one value per hour ({hours}).")
    for index, value in enumerate(values):
        if value is None:
            continue
        if not _is_number(value) or not math.isfinite(value) or value < 0:
            raise serializers.ValidationError(
                f"{where}.{name}[{index}] must be a finite number of 0 or more, or null."
            )


def _check_entry(index: int, entry) -> tuple[float, float]:
    where = f"weather[{index}]"
    if not isinstance(entry, dict):
        raise serializers.ValidationError(f"{where} must be an object.")
    if set(entry) != KEYS:
        raise serializers.ValidationError(f"{where} must have exactly these keys: {', '.join(sorted(KEYS))}.")
    lat, lon = entry["lat"], entry["lon"]
    if not (_is_number(lat) and _is_number(lon) and math.isfinite(lat) and math.isfinite(lon)):
        raise serializers.ValidationError(f"{where}.lat and {where}.lon must be finite numbers.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise serializers.ValidationError(f"{where}.lat or {where}.lon is out of range.")
    _check_times(where, entry["time"])
    for name in ARRAYS:
        _check_values(where, name, entry[name], len(entry["time"]))
    return grid_cell(lat, lon)


class WeatherField(serializers.Field):
    """Validated weather as {grid cell: {hour: WeatherSample}}, built by the same code that parses
    Open-Meteo's own answer (rain plus showers; a null stays unknown)."""

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError("weather must be a list of cells.")
        if len(data) > max_cells():
            raise serializers.ValidationError(f"weather may hold at most {max_cells()} cells.")
        cells = [_check_entry(index, entry) for index, entry in enumerate(data)]
        if len(set(cells)) != len(cells):
            raise serializers.ValidationError("weather holds two entries for the same 0.1 degree grid cell.")
        series = parse_forecast([{"hourly": {"time": e["time"], **{a: e[a] for a in ARRAYS}}} for e in data])
        return dict(zip(cells, series))

    def to_representation(self, value):  # requests only
        raise NotImplementedError
