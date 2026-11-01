"""Open-Meteo adapter. Weather data by Open-Meteo.com (CC BY 4.0)."""

import contextvars
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

import httpx

from domain.geo import grid_cell
from domain.models import WeatherSample

from .constants import (
    DEFAULT_WEATHER_CACHE_TTL_S,
    MAX_FORECAST_DAYS,
    OPEN_METEO_HOURLY,
    OPEN_METEO_URL,
    RETRY_BACKOFF_S,
    WEATHER_BATCH_SIZE,
    WEATHER_MAX_WORKERS,
    WEATHER_RATE_LIMIT_DELAYS_S,
    WEATHER_RATE_LIMIT_JITTER_S,
    WEATHER_REASON_MAX_CHARS,
    WEATHER_TIMEOUT_S,
)
from .errors import WeatherRateLimitedError, WeatherUnavailableError
from .interfaces import Cache, Cell, LatLon, Series, WeatherResult
from .request_context import request_id_var

logger = logging.getLogger("routecast.weather")

_URL = re.compile(r"\S*://\S*")
MESSAGE_RETRY_SOON = "The weather service is rate limited; try again in a minute."
MESSAGE_RETRY_LATER = "The weather service is rate limited; try again later."


def _utc(text: str) -> datetime:
    """Open-Meteo times carry no zone suffix; we request GMT, so they are UTC."""
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(values: list, index: int) -> float | None:
    """A null (or absent) value stays None; it is never treated as 0."""
    value = values[index] if index < len(values) else None
    return None if value is None else float(value)


def _rain(rain: float | None, showers: float | None) -> float | None:
    """Rain for the rules is rain plus showers. If either part is unknown the
    sum is unknown: counting the missing part as 0 would understate the risk."""
    if rain is None or showers is None:
        return None
    return rain + showers


def _parse_location(location: dict) -> dict[datetime, WeatherSample]:
    hourly = location["hourly"]
    wind = hourly.get("wind_speed_10m") or []
    rain = hourly.get("rain") or []
    showers = hourly.get("showers") or []
    snow = hourly.get("snowfall") or []
    series = {}
    # Each value is paired with its own timestamp from the "time" array, so a
    # missing hour is simply absent from the mapping.
    for i, text in enumerate(hourly["time"]):
        series[_utc(text)] = WeatherSample(
            wind_mph=_number(wind, i),
            rain_in_hr=_rain(_number(rain, i), _number(showers, i)),
            snow_in_hr=_number(snow, i),
        )
    return series


def parse_forecast(body: dict | list) -> list[dict[datetime, WeatherSample]]:
    """One hourly mapping per location, in request order. Open-Meteo answers a
    single location with an object and several with a list."""
    locations = body if isinstance(body, list) else [body]
    return [_parse_location(location) for location in locations]


def forecast_days_for(latest_hour: datetime, now: datetime) -> int:
    """Forecast days to request so the series reaches `latest_hour`.

    The series starts at 00:00 UTC today, so day N+1 is needed for any hour on
    day N. That equals the rounded-up day count except at an exact midnight,
    where rounding up would leave out the very hour needed. Capped at 16.
    """
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    days = (latest_hour.astimezone(timezone.utc) - today) // timedelta(days=1) + 1
    return max(1, min(days, MAX_FORECAST_DAYS))


def _parse_batch(response: httpx.Response, expected: int) -> list[dict[datetime, WeatherSample]] | None:
    """The parsed series, or None if the body is malformed or has the wrong number of locations."""
    try:
        parsed = parse_forecast(response.json())
    except (ValueError, KeyError, TypeError):
        return None
    return parsed if len(parsed) == expected else None


def rate_limit_reason(response: httpx.Response) -> str:
    """The "reason" of a 429 body, made safe to log: one line, URLs removed, at
    most 200 characters. It is for the logs only and never reaches the API client."""
    try:
        reason = response.json().get("reason")
    except (ValueError, AttributeError):
        return ""
    if not isinstance(reason, str):
        return ""
    return " ".join(_URL.sub("[url]", reason).split())[:WEATHER_REASON_MAX_CHARS]


def rate_limit_kind(reason: str) -> str:
    """minutely, hourly or daily from the reason text, else unknown."""
    lowered = reason.lower()
    for kind in ("minutely", "hourly", "daily"):
        if kind in lowered:
            return kind
    return "unknown"


def _cache_key(cell: Cell) -> str:
    return f"weather:{cell[0]:.1f}:{cell[1]:.1f}"


class OpenMeteoWeatherProvider:
    def __init__(
        self,
        client: httpx.Client,
        cache: Cache,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        ttl_s: int = DEFAULT_WEATHER_CACHE_TTL_S,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] = lambda limit: random.uniform(0, limit),
    ):
        self._client = client
        self._cache = cache
        self._clock = clock
        self._ttl_s = ttl_s
        self._sleep = sleep
        self._jitter = jitter

    def get_series(self, points: Iterable[LatLon], latest_hour: datetime) -> WeatherResult:
        if latest_hour.utcoffset() is None:
            raise ValueError("latest_hour must be timezone-aware")
        cells = list(dict.fromkeys(grid_cell(lat, lon) for lat, lon in points))

        series: dict[Cell, Series] = {}
        missing: list[Cell] = []
        for cell in cells:
            cached = self._cache.get(_cache_key(cell))
            # A cached series only helps if it reaches the hour we need.
            if cached and max(cached) >= latest_hour:
                series[cell] = cached
            else:
                missing.append(cell)

        failed: set[Cell] = set()
        if missing:
            days = forecast_days_for(latest_hour, self._clock())
            batches = [
                missing[i : i + WEATHER_BATCH_SIZE]
                for i in range(0, len(missing), WEATHER_BATCH_SIZE)
            ]
            with ThreadPoolExecutor(max_workers=WEATHER_MAX_WORKERS) as pool:
                # Each worker gets a copy of the context so its log lines carry the request id.
                futures = [
                    pool.submit(contextvars.copy_context().run, self._fetch_batch, batch, days)
                    for batch in batches
                ]
                outcomes = [future.result() for future in futures]
            for batch, fetched in zip(batches, outcomes):
                if fetched is None:
                    failed.update(batch)
                    continue
                for cell, cell_series in zip(batch, fetched):
                    series[cell] = cell_series
                    self._cache.set(_cache_key(cell), cell_series, self._ttl_s)

        if failed and not series:
            raise WeatherUnavailableError("The weather service failed for every location.")
        return WeatherResult(series, frozenset(failed))

    def _fetch_batch(self, cells: list[Cell], days: int) -> list[dict[datetime, WeatherSample]] | None:
        """Parsed series for each cell in order, or None if the batch failed twice."""
        params = {
            "latitude": ",".join(f"{lat:.1f}" for lat, _ in cells),
            "longitude": ",".join(f"{lon:.1f}" for _, lon in cells),
            "hourly": OPEN_METEO_HOURLY,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "forecast_days": days,
        }
        failures = 0
        rate_limit_delays = iter(WEATHER_RATE_LIMIT_DELAYS_S)
        while True:
            try:
                response = self._client.get(OPEN_METEO_URL, params=params, timeout=WEATHER_TIMEOUT_S)
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code == 429:
                reason = rate_limit_reason(response)
                kind = rate_limit_kind(reason)
                logger.warning(
                    "weather rate limited request_id=%s kind=%s reason=%r", request_id_var.get(), kind, reason
                )
                # Only a per-minute limit clears quickly enough to be worth waiting for.
                delay = next(rate_limit_delays, None) if kind == "minutely" else None
                if delay is None:
                    raise WeatherRateLimitedError(
                        MESSAGE_RETRY_SOON if kind == "minutely" else MESSAGE_RETRY_LATER
                    )
                self._sleep(delay + self._jitter(WEATHER_RATE_LIMIT_JITTER_S))
                continue
            if response is not None:
                if response.status_code == 200:
                    parsed = _parse_batch(response, len(cells))
                    if parsed is not None:
                        return parsed
                elif response.status_code < 500:
                    return None  # a client error will not improve on retry
            failures += 1
            if failures >= 2:
                return None
            self._sleep(RETRY_BACKOFF_S)
