"""Scenario builders for the API tests: fake routes and fake weather, no network."""

from datetime import datetime, timedelta, timezone

from domain.geo import grid_cell
from domain.models import WeatherSample
from domain.tests.factories import route_through
from providers.fakes import FakeRoutingProvider
from providers.interfaces import RoutingResult, WeatherResult

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 12, 30, tzinfo=UTC)
DEPARTURE = datetime(2026, 11, 2, 14, 0, tzinfo=UTC)
REQUEST_ID = "00000000000000000000000000000001"

ORIGIN = (30.0, -100.0)
DESTINATION = (30.0, -96.0)  # about 230 miles east

CALM = WeatherSample(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=0.0)


def wind(mph):
    return WeatherSample(wind_mph=mph, rain_in_hr=0.0, snow_in_hr=0.0)


class ScenarioWeather:
    """A weather provider that answers for any cell: `sample_for(cell, hour)`
    gives the sample (or None for no data), and nothing exists after `until`."""

    def __init__(self, sample_for, until=None, failed=(), error=None):
        self.sample_for = sample_for
        self.until = until
        self.failed = frozenset(failed)
        self.error = error
        self.calls = []

    def get_series(self, points, latest_hour):
        points = list(points)
        self.calls.append((points, latest_hour))
        if self.error is not None:
            raise self.error
        first = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        hours = []
        hour = first
        while hour <= latest_hour:
            if self.until is None or hour <= self.until:
                hours.append(hour)
            hour += timedelta(hours=1)
        cells = list(dict.fromkeys(grid_cell(lat, lon) for lat, lon in points))
        series = {}
        for cell in cells:
            if cell in self.failed:
                continue
            samples = {h: self.sample_for(cell, h) for h in hours}
            series[cell] = {h: s for h, s in samples.items() if s is not None}
        return WeatherResult(series, frozenset(c for c in cells if c in self.failed))


def calm(cell, hour):
    return CALM


def uniform(sample):
    return lambda cell, hour: sample


# Three ways from ORIGIN to DESTINATION: A is straight and fastest, B bends north, C bends south.
LINE_A = [ORIGIN, (30.0, -98.0), DESTINATION]
LINE_B = [ORIGIN, (31.0, -98.0), DESTINATION]
LINE_C = [ORIGIN, (29.0, -98.0), DESTINATION]


def routes(*lines_with_pace, warnings=()):
    """A FakeRoutingProvider returning one route per (line, seconds_per_mile)."""
    built = [
        route_through(line, route_id=f"route-{i + 1}", label=f"Route {chr(65 + i)}", seconds_per_mile=pace)
        for i, (line, pace) in enumerate(lines_with_pace)
    ]
    return FakeRoutingProvider(RoutingResult(tuple(built), tuple(warnings)))


def three_routes():
    return routes((LINE_A, 60.0), (LINE_B, 62.0), (LINE_C, 64.0))


def two_routes():
    return routes((LINE_A, 60.0), (LINE_B, 62.0))


def storm_on_route_a(cell, hour):
    """50 mph wind over the middle of the straight route only."""
    lat, lon = cell
    if abs(lat - 30.0) < 0.1 and -99.3 < lon < -97.0:
        return wind(50.0)
    return CALM


def analyze_payload(**overrides):
    payload = {
        "origin": {"lat": ORIGIN[0], "lon": ORIGIN[1], "label": "Origin"},
        "destination": {"lat": DESTINATION[0], "lon": DESTINATION[1], "label": "Destination"},
        "departure_time": "2026-11-02T14:00:00Z",
        "load_weight_lb": 10_000,
    }
    payload.update(overrides)
    return payload


def heatmap_payload(**overrides):
    payload = {
        "points": [[30.0, -99.0], [30.0, -98.0]],
        "departure_time": "2026-11-02T14:00:00Z",
        "load_weight_lb": 10_000,
    }
    payload.update(overrides)
    return payload
