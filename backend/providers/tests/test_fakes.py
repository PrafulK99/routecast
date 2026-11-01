from datetime import datetime, timezone

import pytest

from domain.geo import grid_cell
from domain.models import WeatherSample
from providers.errors import NoRouteError, WeatherRateLimitedError
from providers.fakes import FakeRoutingProvider, FakeWeatherProvider, InMemoryCache
from providers.interfaces import RoutingResult

from domain.tests.factories import straight_route

HOUR = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
SAMPLE = WeatherSample(10, 0, 0)


def test_fake_routing_returns_its_result_and_records_calls():
    result = RoutingResult((straight_route(80),), ("warning",))
    fake = FakeRoutingProvider(result)

    assert fake.get_routes((1.0, 2.0), (3.0, 4.0)) is result
    assert fake.calls == [((1.0, 2.0), (3.0, 4.0))]


def test_fake_routing_can_raise():
    with pytest.raises(NoRouteError):
        FakeRoutingProvider(error=NoRouteError("none")).get_routes((1.0, 2.0), (3.0, 4.0))


def test_fake_weather_serves_known_cells_and_reports_the_rest_failed():
    known = grid_cell(32.8, -96.8)
    fake = FakeWeatherProvider({known: {HOUR: SAMPLE}})

    result = fake.get_series([(32.81, -96.79), (41.9, -87.6)], HOUR)

    assert result.series == {known: {HOUR: SAMPLE}}
    assert result.failed_cells == frozenset({grid_cell(41.9, -87.6)})
    assert fake.calls == [([(32.81, -96.79), (41.9, -87.6)], HOUR)]


def test_fake_weather_can_raise():
    with pytest.raises(WeatherRateLimitedError):
        FakeWeatherProvider(error=WeatherRateLimitedError("slow down")).get_series([(1.0, 2.0)], HOUR)


def test_in_memory_cache_stores_values_and_timeouts():
    cache = InMemoryCache()

    cache.set("k", {"a": 1}, 600)

    assert cache.get("k") == {"a": 1}
    assert cache.get("missing") is None
    assert cache.timeouts["k"] == 600
