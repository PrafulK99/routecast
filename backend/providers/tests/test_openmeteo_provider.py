import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from domain.geo import grid_cell
from providers.errors import WeatherRateLimitedError, WeatherUnavailableError
from providers.fakes import InMemoryCache
from providers.openmeteo import OpenMeteoWeatherProvider, forecast_days_for

from .helpers import json_response, openmeteo_body

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 19, 43, tzinfo=UTC)
TONIGHT = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)


def at(day, hour=0):
    return datetime(2026, 11, day, hour, tzinfo=UTC)


class Stub:
    """Open-Meteo stand-in: answers any request with the recorded series, one
    location per requested coordinate. `respond` can override a response."""

    def __init__(self, respond=None, delay=0.0):
        self.requests = []
        self.respond = respond
        self.delay = delay
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0

    def __call__(self, request):
        with self._lock:
            self.requests.append(request)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(self.delay)
            if self.respond:
                override = self.respond(request)
                if override is not None:
                    return override
            count = len(request.url.params["latitude"].split(","))
            fixture = openmeteo_body()
            locations = [fixture[i % 3] for i in range(count)]
            return json_response(locations[0] if count == 1 else locations)
        finally:
            with self._lock:
                self.in_flight -= 1

    def batch_sizes(self):
        return sorted(len(r.url.params["latitude"].split(",")) for r in self.requests)


def make_provider(stub, cache=None, sleeps=None):
    return OpenMeteoWeatherProvider(
        httpx.Client(transport=httpx.MockTransport(stub)),
        cache if cache is not None else InMemoryCache(),
        clock=lambda: NOW,
        sleep=(sleeps if sleeps is not None else []).append,
    )


def line_of_points(count):
    """`count` points, each in its own 0.1 degree grid cell."""
    return [(30.0 + 0.1 * i, -97.0) for i in range(count)]


# --- forecast_days --------------------------------------------------------------


@pytest.mark.parametrize(
    "latest_hour, expected",
    [
        (at(1, 0), 1),  # the first hour of today
        (TONIGHT, 1),  # later today
        (at(2, 0), 2),  # an exact midnight needs the next day (plain ceil would say 1)
        (at(2, 1), 2),
        (at(3, 19), 3),  # departure 19:00 + 48 h
        (at(17, 0), 16),  # day 17 is past the limit: capped
        (datetime(2027, 3, 1, tzinfo=UTC), 16),
        (at(1, 0) - timedelta(days=3), 1),  # never below one day
    ],
)
def test_forecast_days_cover_the_latest_hour_needed(latest_hour, expected):
    assert forecast_days_for(latest_hour, NOW) == expected


def test_forecast_days_follow_the_utc_date_not_the_local_one():
    late_in_utah = datetime(2026, 11, 1, 20, 0, tzinfo=timezone(timedelta(hours=-7)))  # 03:00 UTC on 2 Nov

    assert forecast_days_for(at(3, 2), late_in_utah) == 2


# --- request --------------------------------------------------------------------


def test_request_asks_for_the_specified_variables_and_units():
    stub = Stub()

    make_provider(stub).get_series([(32.7767, -96.7970), (35.4676, -97.5164)], at(3, 19))

    (request,) = stub.requests
    assert request.url.host == "api.open-meteo.com"
    assert dict(request.url.params) == {
        "latitude": "32.8,35.5",
        "longitude": "-96.8,-97.5",
        "hourly": "wind_speed_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "forecast_days": "3",
    }
    assert request.extensions["timeout"]["read"] == 5.0


def test_points_in_the_same_grid_cell_share_one_lookup():
    stub = Stub()
    points = [(32.71, -96.74), (32.74, -96.69), (32.7, -96.7)]

    result = make_provider(stub).get_series(points, TONIGHT)

    assert stub.batch_sizes() == [1]
    assert list(result.series) == [grid_cell(32.7, -96.7)]


def test_results_are_keyed_by_grid_cell_in_input_order():
    cells = [grid_cell(lat, lon) for lat, lon in line_of_points(5)]

    result = make_provider(Stub()).get_series(line_of_points(5), TONIGHT)

    assert list(result.series) == cells
    assert result.failed_cells == frozenset()
    assert all(len(series) == 48 for series in result.series.values())


def test_no_points_makes_no_request():
    stub = Stub()

    result = make_provider(stub).get_series([], TONIGHT)

    assert stub.requests == [] and result.series == {} and result.failed_cells == frozenset()


def test_a_naive_latest_hour_is_rejected():
    with pytest.raises(ValueError):
        make_provider(Stub()).get_series([(32.8, -96.8)], datetime(2026, 11, 1, 23, 0))


# --- batching and parallelism ---------------------------------------------------


def test_locations_are_sent_in_batches_of_at_most_50():
    stub = Stub()

    result = make_provider(stub).get_series(line_of_points(120), TONIGHT)

    assert stub.batch_sizes() == [20, 50, 50]
    assert len(result.series) == 120


def test_at_most_four_requests_run_in_parallel():
    stub = Stub(delay=0.05)

    make_provider(stub).get_series(line_of_points(250), TONIGHT)  # 5 batches

    assert len(stub.requests) == 5
    assert 2 <= stub.max_in_flight <= 4


# --- failures -------------------------------------------------------------------


def test_429_raises_a_rate_limit_error_with_no_retry():
    stub = Stub(lambda request: httpx.Response(429, json={"error": True, "reason": "Too many requests"}))
    sleeps = []

    with pytest.raises(WeatherRateLimitedError):
        make_provider(stub, sleeps=sleeps).get_series([(32.8, -96.8)], TONIGHT)

    assert len(stub.requests) == 1
    assert sleeps == []


def test_429_on_several_batches_is_never_retried():
    stub = Stub(lambda request: httpx.Response(429, json={"error": True}))

    with pytest.raises(WeatherRateLimitedError):
        make_provider(stub).get_series(line_of_points(120), TONIGHT)

    assert len(stub.requests) <= 3  # one attempt per batch, no retries


def test_one_retry_after_a_server_error_then_success():
    failures = iter([httpx.Response(500)])
    stub = Stub(lambda request: next(failures, None))
    sleeps = []

    result = make_provider(stub, sleeps=sleeps).get_series([(32.8, -96.8)], TONIGHT)

    assert len(stub.requests) == 2
    assert sleeps == [0.5]
    assert len(result.series) == 1


def test_a_transport_error_is_retried_once():
    attempts = []

    def respond(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("boom")

    result = make_provider(Stub(respond)).get_series([(32.8, -96.8)], TONIGHT)

    assert len(attempts) == 2 and len(result.series) == 1


def test_a_batch_that_fails_twice_marks_only_its_cells_failed():
    # The third batch (latitudes 40.0 and up) always fails.
    stub = Stub(lambda r: httpx.Response(503) if float(r.url.params["latitude"].split(",")[0]) >= 40 else None)
    points = line_of_points(120)

    result = make_provider(stub).get_series(points, TONIGHT)

    assert result.failed_cells == frozenset(grid_cell(*p) for p in points[100:])
    assert set(result.series) == {grid_cell(*p) for p in points[:100]}


def test_every_cell_failing_raises_weather_unavailable():
    stub = Stub(lambda request: httpx.Response(500))

    with pytest.raises(WeatherUnavailableError):
        make_provider(stub).get_series(line_of_points(60), TONIGHT)


def test_a_client_error_is_not_retried():
    stub = Stub(lambda request: httpx.Response(400, json={"error": True, "reason": "bad"}))

    with pytest.raises(WeatherUnavailableError):
        make_provider(stub).get_series([(32.8, -96.8)], TONIGHT)

    assert len(stub.requests) == 1


def test_a_response_with_the_wrong_number_of_locations_fails_the_batch():
    stub = Stub(lambda request: json_response(openmeteo_body()[:1]))

    with pytest.raises(WeatherUnavailableError):
        make_provider(stub).get_series(line_of_points(3), TONIGHT)

    assert len(stub.requests) == 2  # retried once


def test_garbage_in_the_body_fails_the_batch():
    stub = Stub(lambda request: httpx.Response(200, content=b"not json"))

    with pytest.raises(WeatherUnavailableError):
        make_provider(stub).get_series([(32.8, -96.8)], TONIGHT)


# --- cache ----------------------------------------------------------------------


def test_each_cell_series_is_cached_for_30_minutes():
    cache = InMemoryCache()

    make_provider(Stub(), cache).get_series([(32.8, -96.8), (35.5, -97.5)], TONIGHT)

    assert set(cache.values) == {"weather:32.8:-96.8", "weather:35.5:-97.5"}
    assert set(cache.timeouts.values()) == {1800}


def test_cached_cells_are_not_fetched_again():
    cache = InMemoryCache()
    first = Stub()
    make_provider(first, cache).get_series([(32.8, -96.8), (35.5, -97.5)], TONIGHT)

    second = Stub()
    result = make_provider(second, cache).get_series([(32.8, -96.8), (35.5, -97.5)], TONIGHT)

    assert second.requests == []
    assert len(result.series) == 2


def test_only_the_missing_cells_are_requested():
    cache = InMemoryCache()
    make_provider(Stub(), cache).get_series([(32.8, -96.8)], TONIGHT)
    stub = Stub()

    result = make_provider(stub, cache).get_series([(32.8, -96.8), (35.5, -97.5)], TONIGHT)

    (request,) = stub.requests
    assert request.url.params["latitude"] == "35.5"
    assert len(result.series) == 2


def test_a_cached_series_that_stops_short_of_the_needed_hour_is_refetched():
    cache = InMemoryCache()
    make_provider(Stub(), cache).get_series([(32.8, -96.8)], TONIGHT)  # series ends 2 Nov 23:00
    stub = Stub()

    make_provider(stub, cache).get_series([(32.8, -96.8)], at(5, 12))

    (request,) = stub.requests
    assert request.url.params["forecast_days"] == "5"


def test_a_failed_batch_is_not_cached():
    cache = InMemoryCache()
    stub = Stub(lambda request: httpx.Response(500))

    with pytest.raises(WeatherUnavailableError):
        make_provider(stub, cache).get_series([(32.8, -96.8)], TONIGHT)

    assert cache.values == {}
