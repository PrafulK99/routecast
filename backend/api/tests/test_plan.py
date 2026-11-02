"""POST /api/plan: which weather an analysis needs. It fetches none."""

from datetime import timedelta

import httpx
import pytest

from domain.geo import grid_cell
from providers.fakes import FakeRoutingProvider, InMemoryCache
from providers.mapbox import MapboxRoutingProvider
from providers.errors import NoRouteError
from providers.tests.helpers import json_response, mapbox_body
from services import container

from .helpers import DEPARTURE, ScenarioWeather, analyze_payload, calm, three_routes, two_routes

URL = "/api/plan"


def plan(client, **overrides):
    response = client.post(URL, analyze_payload(**overrides), format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def test_plan_lists_the_unique_cells_of_every_checkpoint_of_every_route(client, providers):
    providers(three_routes())

    body = plan(client)
    analysis = client.post("/api/analyze", analyze_payload(), format="json").json()

    expected = {
        grid_cell(cp["lat"], cp["lon"]) for route in analysis["routes"] for cp in route["checkpoints"]
    }
    cells = [tuple(cell) for cell in body["cells"]]
    assert set(body) == {"cells", "window"}
    assert len(cells) == len(set(cells)) and set(cells) == expected


def test_plan_window_runs_from_the_first_forecast_hour_to_48_hours_after_departure(client, providers):
    providers(two_routes())

    window = plan(client)["window"]

    assert window == {
        "first_hour": "2026-11-02T14:00:00Z",
        "last_hour": (DEPARTURE + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_plan_makes_no_weather_call(client, providers):
    _, weather = providers(three_routes(), ScenarioWeather(calm))

    plan(client)

    assert weather.calls == []


def test_a_later_analyze_repeats_none_of_the_routing_calls(client, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return json_response(mapbox_body())

    routing = MapboxRoutingProvider("pk.test", httpx.Client(transport=httpx.MockTransport(handler)), InMemoryCache())
    monkeypatch.setattr(container, "routing_provider", lambda: routing)
    monkeypatch.setattr(container, "weather_provider", lambda: ScenarioWeather(calm))

    plan(client)
    after_plan = len(requests)
    response = client.post("/api/analyze", analyze_payload(), format="json")

    assert response.status_code == 200
    assert after_plan >= 1 and len(requests) == after_plan


def test_plan_validates_like_analyze(client, providers):
    providers()

    response = client.post(URL, analyze_payload(load_weight_lb=-1), format="json")

    assert response.status_code == 400
    assert "load_weight_lb" in response.json()["error"]["fields"]


def test_plan_reports_a_trip_with_no_route(client, monkeypatch):
    monkeypatch.setattr(container, "routing_provider", lambda: FakeRoutingProvider(error=NoRouteError("none")))

    response = client.post(URL, analyze_payload(), format="json")

    assert response.status_code == 422 and response.json()["error"]["code"] == "no_route"
