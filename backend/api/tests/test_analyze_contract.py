"""The /api/analyze response contract, interval handling, geometry and logging."""

import logging
import math
from datetime import timedelta

import pytest

from domain.geo import grid_cell
from domain.tests.factories import route_through
from providers.errors import WeatherUnavailableError
from providers.fakes import FakeRoutingProvider
from providers.interfaces import RoutingResult

from .helpers import (
    DEPARTURE,
    DESTINATION,
    ORIGIN,
    REQUEST_ID,
    ScenarioWeather,
    analyze_payload,
    calm,
    routes,
    storm_on_route_a,
    three_routes,
    two_routes,
    LINE_A,
)

URL = "/api/analyze"


def analyze(client, **overrides):
    response = client.post(URL, analyze_payload(**overrides), format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def test_response_has_exactly_the_documented_keys(client, providers):
    providers(two_routes(), ScenarioWeather(storm_on_route_a))

    body = analyze(client)

    assert set(body) == {"meta", "routes", "recommendation", "corridor_points"}
    assert set(body["meta"]) == {
        "request_id", "interval_miles", "truck_duration_factor", "forecast_source", "warnings"
    }
    route = body["routes"][0]
    assert set(route) == {
        "id", "label", "distance_mi", "duration_s", "departure_time", "arrival_time",
        "geometry", "summary", "checkpoints",
    }
    assert set(route["summary"]) == {
        "miles_by_level", "avg_risk", "worst_level", "worst_level_name", "coverage_pct", "blocked"
    }
    assert set(route["summary"]["miles_by_level"]) == {"low", "moderate", "high", "severe", "no_travel"}
    checkpoint = route["checkpoints"][0]
    assert set(checkpoint) == {
        "index", "mile", "lat", "lon", "eta", "forecast_hour", "wind_mph", "rain_in_hr",
        "snow_in_hr", "segment_mi", "status", "risk",
    }
    assert set(checkpoint["risk"]) == {
        "level", "level_name", "factor", "wind_level", "rain_level", "snow_level", "load_rule_applied"
    }
    assert set(body["recommendation"]) == {"route_id", "reasons", "all_blocked", "ranking"}
    assert set(body["recommendation"]["ranking"][0]) == {"rank", "route_id", "sort_key"}
    assert set(body["recommendation"]["ranking"][0]["sort_key"]) == {
        "no_travel_mi", "severe_mi", "high_mi", "avg_risk", "duration_s"
    }


def test_meta_values_and_request_id(client, providers):
    providers()

    response = client.post(URL, analyze_payload(), format="json")

    meta = response.json()["meta"]
    assert meta["request_id"] == REQUEST_ID == response["X-Request-ID"]
    assert meta["interval_miles"] == 25
    assert meta["truck_duration_factor"] == 1.1
    assert meta["forecast_source"] == "open-meteo"


def test_route_times_and_checkpoints(client, providers):
    providers(three_routes())

    route = analyze(client)["routes"][0]

    assert route["departure_time"] == "2026-11-02T14:00:00Z"
    assert route["arrival_time"] == route["checkpoints"][-1]["eta"]
    assert route["checkpoints"][0]["eta"] == route["departure_time"]
    assert [cp["index"] for cp in route["checkpoints"]] == list(range(len(route["checkpoints"])))
    assert route["checkpoints"][0]["mile"] == 0 and route["checkpoints"][-1]["mile"] == pytest.approx(route["distance_mi"], abs=0.1)
    assert sum(cp["segment_mi"] for cp in route["checkpoints"]) == pytest.approx(route["distance_mi"], abs=0.5)


def test_truck_factor_comes_from_settings(client, providers, settings):
    providers(routes((LINE_A, 60.0)))
    settings.TRUCK_DURATION_FACTOR = 1.0
    plain = analyze(client)

    settings.TRUCK_DURATION_FACTOR = 1.25
    slower = analyze(client)

    assert slower["meta"]["truck_duration_factor"] == 1.25
    assert slower["routes"][0]["duration_s"] == pytest.approx(plain["routes"][0]["duration_s"] * 1.25, abs=1)
    assert slower["routes"][0]["arrival_time"] > plain["routes"][0]["arrival_time"]


def test_the_requested_interval_sets_checkpoint_spacing(client, providers):
    providers(routes((LINE_A, 60.0)))

    body = analyze(client, checkpoint_interval_miles=10)

    miles = [cp["mile"] for cp in body["routes"][0]["checkpoints"]]
    assert body["meta"]["interval_miles"] == 10
    assert miles[:4] == [0, 10, 20, 30]


def test_the_interval_is_raised_for_a_long_route_and_reported(client, providers, settings):
    providers(routes((LINE_A, 60.0)))
    settings.MAX_CHECKPOINTS_PER_ROUTE = 12  # 10-mile spacing would give 25 checkpoints

    body = analyze(client, checkpoint_interval_miles=10)

    assert body["meta"]["interval_miles"] == 25
    assert len(body["routes"][0]["checkpoints"]) <= 12
    assert any("raised from 10 to 25" in w for w in body["meta"]["warnings"])


def test_routing_warnings_are_passed_through(client, providers):
    providers(routes((LINE_A, 60.0), warnings=["Only 1 route could be found."]))

    assert analyze(client)["meta"]["warnings"] == ["Only 1 route could be found."]


def test_a_failed_weather_location_becomes_unavailable_with_a_warning(client, providers):
    providers(two_routes(), ScenarioWeather(calm, failed={grid_cell(*ORIGIN)}))

    body = analyze(client)

    assert any("could not be fetched for 1 location" in w for w in body["meta"]["warnings"])
    for route in body["routes"]:
        first = route["checkpoints"][0]
        assert first["status"] == "unavailable" and first["risk"]["level"] is None
        assert route["checkpoints"][1]["status"] == "ok"


def test_providers_are_called_once_with_the_request(client, providers):
    routing, weather = providers(two_routes())

    analyze(client)

    assert routing.calls == [(ORIGIN, DESTINATION)]
    assert len(weather.calls) == 1
    points, latest_hour = weather.calls[0]
    # Far enough for the 48-hour heatmap that follows, so its request hits the cache.
    assert latest_hour == DEPARTURE + timedelta(hours=48)
    assert len(points) > 10


def test_the_same_trip_twice_gives_identical_results(client, providers):
    providers(two_routes(), ScenarioWeather(storm_on_route_a))

    first = client.post(URL, analyze_payload(), format="json").json()
    second = client.post(URL, analyze_payload(), format="json").json()

    assert first == second


# --- geometry and corridor points ----------------------------------------------


def long_route(vertices):
    """A wobbly 600-mile route with many vertices, like a real Mapbox response."""
    points = [
        (30.0 + 8.0 * i / vertices, -100.0 + 0.003 * math.sin(i / 25) + 4.0 * i / vertices)
        for i in range(vertices + 1)
    ]
    return FakeRoutingProvider(RoutingResult((route_through(points, "route-1", "Route A"),)))


def test_display_geometry_is_simplified_but_keeps_the_ends(client, providers):
    routing = long_route(13_000)
    providers(routing)
    full = routing.get_routes(ORIGIN, DESTINATION).routes[0].geometry

    route = analyze(client)["routes"][0]

    coordinates = route["geometry"]["coordinates"]
    assert route["geometry"]["type"] == "LineString"
    assert 2 < len(coordinates) <= 2000 < len(full)
    assert coordinates[0] == [round(full[0][1], 5), round(full[0][0], 5)]  # [lon, lat]
    assert coordinates[-1] == [round(full[-1][1], 5), round(full[-1][0], 5)]


def test_the_full_geometry_never_appears_in_the_response(client, providers):
    providers(long_route(13_000))

    response = client.post(URL, analyze_payload(), format="json")

    assert len(response.content) < 400_000


def test_corridor_points_are_capped_pairs(client, providers):
    line = [(30.0, -110.0), (30.0, -85.0), (30.0, -60.0)]  # about 3,000 miles
    providers(routes((line, 60.0)))

    points = analyze(client)["corridor_points"]

    assert 2 < len(points) <= 120
    assert all(len(point) == 2 and -90 <= point[0] <= 90 and -180 <= point[1] <= 180 for point in points)


# --- logging --------------------------------------------------------------------


def test_each_request_logs_its_id_and_upstream_timings(client, providers, caplog):
    providers()
    caplog.set_level(logging.INFO)

    client.post(URL, analyze_payload(), format="json")

    analyze_line = next(r.getMessage() for r in caplog.records if r.name == "routecast.analyze")
    assert f"request_id={REQUEST_ID}" in analyze_line
    assert "mapbox_ms=" in analyze_line and "open_meteo_ms=" in analyze_line
    access_line = next(r.getMessage() for r in caplog.records if r.name == "routecast.request")
    assert f"request_id={REQUEST_ID}" in access_line and "status=200" in access_line


def test_timings_are_logged_when_an_upstream_call_fails(client, providers, caplog):
    providers(weather=ScenarioWeather(calm, error=WeatherUnavailableError("down")))
    caplog.set_level(logging.INFO)

    response = client.post(URL, analyze_payload(), format="json")

    assert response.status_code == 502
    line = next(r.getMessage() for r in caplog.records if r.name == "routecast.analyze")
    assert f"request_id={REQUEST_ID}" in line and "open_meteo_ms=" in line


def test_logs_hold_no_coordinates_or_labels(client, providers, caplog):
    providers()
    caplog.set_level(logging.INFO)

    client.post(URL, analyze_payload(), format="json")

    text = " ".join(r.getMessage() for r in caplog.records)
    assert "-100.0" not in text and "Origin" not in text and "30.0" not in text
