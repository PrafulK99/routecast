"""The five scenario fixtures from docs/DESIGN.md (Testing), through the endpoint."""

import re
from datetime import timedelta

import pytest

from .helpers import (
    DEPARTURE,
    ScenarioWeather,
    analyze_payload,
    calm,
    storm_on_route_a,
    three_routes,
    two_routes,
    uniform,
    wind,
)

URL = "/api/analyze"


def analyze(client, **overrides):
    response = client.post(URL, analyze_payload(**overrides), format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def route_by_id(body, route_id):
    return next(route for route in body["routes"] if route["id"] == route_id)


# 1. Calm day: all routes Low; the shortest wins on time.
def test_calm_day_recommends_the_fastest_route(client, providers):
    providers(three_routes(), ScenarioWeather(calm))

    body = analyze(client)

    assert [r["summary"]["worst_level"] for r in body["routes"]] == [0, 0, 0]
    assert all(r["summary"]["coverage_pct"] == 100 and not r["summary"]["blocked"] for r in body["routes"])
    recommendation = body["recommendation"]
    assert recommendation["route_id"] == "route-1"
    assert recommendation["all_blocked"] is False
    assert re.fullmatch(
        r"Weather is equal on both routes; Route A is \d+ minutes faster\.", recommendation["reasons"][0]
    )
    assert [entry["route_id"] for entry in recommendation["ranking"]] == ["route-1", "route-2", "route-3"]
    assert body["meta"]["warnings"] == []


# 2. Heavy load in 40 mph wind: Severe at 45,000 lb, High at 35,000 lb.
@pytest.mark.parametrize(
    "load, level, name, load_rule",
    [(45_000, 3, "Severe", True), (40_001, 3, "Severe", True), (40_000, 2, "High", False), (35_000, 2, "High", False)],
)
def test_heavy_load_in_40_mph_wind(client, providers, load, level, name, load_rule):
    providers(two_routes(), ScenarioWeather(uniform(wind(40.0))))

    body = analyze(client, load_weight_lb=load)

    for route in body["routes"]:
        assert route["summary"]["worst_level"] == level
        assert route["summary"]["worst_level_name"] == name
        assert all(cp["risk"]["level"] == level for cp in route["checkpoints"])
        assert all(cp["risk"]["load_rule_applied"] is load_rule for cp in route["checkpoints"])
        assert all(cp["risk"]["factor"] == "wind" for cp in route["checkpoints"])
        assert route["summary"]["miles_by_level"][name.lower()] == route["distance_mi"]


# 3. Storm on the fastest route: a slower route with fewer Severe miles is recommended.
def test_storm_on_the_fastest_route_recommends_the_slower_calm_one(client, providers):
    providers(two_routes(), ScenarioWeather(storm_on_route_a))

    body = analyze(client)

    fast, slow = route_by_id(body, "route-1"), route_by_id(body, "route-2")
    assert fast["duration_s"] < slow["duration_s"]
    assert fast["summary"]["miles_by_level"]["severe"] > 100
    assert slow["summary"]["miles_by_level"]["severe"] == 0
    recommendation = body["recommendation"]
    assert recommendation["route_id"] == "route-2"
    assert re.fullmatch(
        r"Route B has 0 Severe miles against \d+(\.\d)? on Route A, and is \d+ minutes slower\.",
        recommendation["reasons"][0],
    )
    ranked = recommendation["ranking"]
    assert [entry["route_id"] for entry in ranked] == ["route-2", "route-1"]
    assert ranked[0]["sort_key"]["severe_mi"] == 0
    assert ranked[1]["sort_key"]["severe_mi"] == fast["summary"]["miles_by_level"]["severe"]


# 4. No Travel on every route: the all_blocked warning appears.
def test_no_travel_on_every_route_sets_all_blocked(client, providers):
    providers(three_routes(), ScenarioWeather(uniform(wind(60.0))))

    body = analyze(client)

    assert all(r["summary"]["blocked"] for r in body["routes"])
    recommendation = body["recommendation"]
    assert recommendation["all_blocked"] is True
    assert recommendation["reasons"][0].startswith("Every route has No Travel conditions.")
    # The least blocked route is the shortest here, since all of every route is blocked.
    assert recommendation["route_id"] == min(body["routes"], key=lambda r: r["distance_mi"])["id"]


# 5. Forecast gap: coverage drops below 100% and later checkpoints are unavailable.
def test_forecast_gap_lowers_coverage_and_marks_checkpoints_unavailable(client, providers):
    providers(two_routes(), ScenarioWeather(calm, until=DEPARTURE + timedelta(hours=2)))

    body = analyze(client)

    for route in body["routes"]:
        unavailable = [cp for cp in route["checkpoints"] if cp["status"] == "unavailable"]
        assert unavailable and len(unavailable) < len(route["checkpoints"])
        assert route["summary"]["coverage_pct"] < 100
        for cp in unavailable:
            # Never a Low rating where the answer is unknown.
            assert cp["risk"]["level"] is None and cp["risk"]["level_name"] is None
            assert cp["wind_mph"] is None and cp["rain_in_hr"] is None and cp["snow_in_hr"] is None
        # Unavailable stretches are left out of the mile totals.
        assert sum(route["summary"]["miles_by_level"].values()) < route["distance_mi"]
    recommended = route_by_id(body, body["recommendation"]["route_id"])
    assert any(
        w.startswith(f"{recommended['label']} has forecast data for")
        and f"{int(recommended['summary']['coverage_pct'])}%" in w
        for w in body["meta"]["warnings"]
    )


def test_no_coverage_warning_when_the_recommended_route_is_fully_covered(client, providers):
    providers(two_routes(), ScenarioWeather(calm))

    assert analyze(client)["meta"]["warnings"] == []
