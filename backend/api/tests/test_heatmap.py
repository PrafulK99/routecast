"""POST /api/heatmap: 49 hourly levels per point, -1 where there is no forecast."""

import logging
from datetime import datetime, timedelta, timezone

from domain.geo import grid_cell
from providers.errors import WeatherRateLimitedError, WeatherUnavailableError

from .helpers import (
    DEPARTURE,
    ScenarioWeather,
    analyze_payload,
    calm,
    heatmap_payload,
    storm_on_route_a,
    two_routes,
    uniform,
    wind,
)

URL = "/api/heatmap"
START = DEPARTURE  # the tests depart on the hour


def heatmap(client, **overrides):
    response = client.post(URL, heatmap_payload(**overrides), format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def test_response_shape_and_hours(client, providers):
    providers(weather=ScenarioWeather(calm))

    body = heatmap(client)

    assert set(body) == {"start_hour", "hours", "points"}
    assert body["hours"] == 49
    assert [set(p) for p in body["points"]] == [{"lat", "lon", "levels"}] * 2
    assert [(p["lat"], p["lon"]) for p in body["points"]] == [(30.0, -99.0), (30.0, -98.0)]
    assert all(len(p["levels"]) == 49 and set(p["levels"]) == {0} for p in body["points"])


def test_start_hour_is_the_departure_rounded_down_to_the_hour(client, providers):
    providers(weather=ScenarioWeather(calm))

    body = heatmap(client, departure_time="2026-11-02T14:40:30Z")

    assert body["start_hour"] == "2026-11-02T14:00:00Z"


def test_the_weather_is_requested_through_the_last_slider_hour(client, providers):
    _, weather = providers(weather=ScenarioWeather(calm))

    heatmap(client, departure_time="2026-11-02T14:40:00Z")

    ((points, latest_hour),) = weather.calls
    assert points == [(30.0, -99.0), (30.0, -98.0)]
    assert latest_hour == START + timedelta(hours=48)


def test_hours_without_a_forecast_are_minus_one(client, providers):
    providers(weather=ScenarioWeather(calm, until=START + timedelta(hours=10)))

    levels = heatmap(client)["points"][0]["levels"]

    assert levels[:11] == [0] * 11
    assert levels[11:] == [-1] * 38


def test_a_hole_in_the_series_is_minus_one_only_at_that_hour(client, providers):
    hole = START + timedelta(hours=7)
    providers(weather=ScenarioWeather(lambda cell, hour: None if hour == hole else wind(30.0)))

    levels = heatmap(client)["points"][0]["levels"]

    assert levels[7] == -1
    assert levels[:7] == [1] * 7 and levels[8:] == [1] * 41


def test_the_load_changes_the_levels(client, providers):
    providers(weather=ScenarioWeather(uniform(wind(40.0))))

    heavy = heatmap(client, load_weight_lb=45_000)["points"][0]["levels"]
    light = heatmap(client, load_weight_lb=35_000)["points"][0]["levels"]

    assert set(heavy) == {3}  # Severe: over 40,000 lb in 35-45 mph wind
    assert set(light) == {2}  # High


def test_a_location_that_failed_is_minus_one_for_every_hour(client, providers):
    providers(weather=ScenarioWeather(calm, failed={grid_cell(30.0, -99.0)}))

    first, second = heatmap(client)["points"]

    assert set(first["levels"]) == {-1}
    assert set(second["levels"]) == {0}


def test_every_location_failing_is_a_502(client, providers):
    providers(weather=ScenarioWeather(calm, error=WeatherUnavailableError("down")))

    response = client.post(URL, heatmap_payload(), format="json")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "weather_unavailable"


def test_a_weather_rate_limit_is_a_503(client, providers):
    providers(weather=ScenarioWeather(calm, error=WeatherRateLimitedError("slow down")))

    response = client.post(URL, heatmap_payload(), format="json")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "weather_rate_limited"


def test_the_heatmap_agrees_with_the_route_scores(client, providers):
    """Same risk function, same load: a checkpoint's level equals the heatmap level
    at its forecast hour."""
    providers(two_routes(), ScenarioWeather(storm_on_route_a))
    analysis = client.post("/api/analyze", analyze_payload(load_weight_lb=20_000), format="json").json()
    checkpoints = analysis["routes"][0]["checkpoints"]
    assert {cp["risk"]["level"] for cp in checkpoints} == {0, 3}  # the storm is in the data

    points = [[cp["lat"], cp["lon"]] for cp in checkpoints]
    body = heatmap(client, points=points, load_weight_lb=20_000)

    start = DEPARTURE
    for checkpoint, point in zip(checkpoints, body["points"]):
        hour = datetime.strptime(checkpoint["forecast_hour"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        index = int((hour - start).total_seconds() // 3600)
        assert point["levels"][index] == checkpoint["risk"]["level"]


def test_heatmap_logs_its_id_and_timing(client, providers, caplog):
    providers(weather=ScenarioWeather(calm))
    caplog.set_level(logging.INFO)

    client.post(URL, heatmap_payload(), format="json")

    line = next(r.getMessage() for r in caplog.records if r.name == "routecast.heatmap")
    assert "request_id=" in line and "open_meteo_ms=" in line
