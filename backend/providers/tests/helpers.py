"""Fixture loading and synthetic response builders for the provider tests."""

import copy
import json
from pathlib import Path
from urllib.parse import unquote

import httpx

from domain.geo import haversine_miles
from providers.constants import METERS_PER_MILE

FIXTURES = Path(__file__).parent / "fixtures"
SPEED_M_PER_S = 25.0


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mapbox_body() -> dict:
    """A fresh copy of the recorded two-route Directions response."""
    return copy.deepcopy(load_fixture("mapbox_two_routes.json")["body"])


def openmeteo_body() -> list:
    """A fresh copy of the recorded three-location Open-Meteo response."""
    return copy.deepcopy(load_fixture("openmeteo_three_cells.json")["body"])


def directions_body(routes: list[list[list[tuple[float, float]]]]) -> dict:
    """A Directions response. Each route is a list of legs; each leg is a list of
    (lat, lon) vertices whose first vertex is the previous leg's last."""
    built = []
    for legs in routes:
        coordinates, leg_data = [], []
        for i, leg in enumerate(legs):
            coordinates += leg if i == 0 else leg[1:]
            meters = [haversine_miles(a, b) * METERS_PER_MILE for a, b in zip(leg, leg[1:])]
            leg_data.append(
                {"annotation": {"distance": meters, "duration": [m / SPEED_M_PER_S for m in meters]}}
            )
        total = sum(sum(leg["annotation"]["distance"]) for leg in leg_data)
        built.append(
            {
                "distance": total,
                "duration": total / SPEED_M_PER_S,
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in coordinates]},
                "legs": leg_data,
            }
        )
    return {"code": "Ok", "routes": built}


def waypoints(request: httpx.Request) -> list[tuple[float, float]]:
    """The (lat, lon) waypoints encoded in a Directions request path."""
    last = unquote(request.url.path).rsplit("/", 1)[-1]
    return [tuple(map(float, pair.split(",")))[::-1] for pair in last.split(";")]


def json_response(body, status=200) -> httpx.Response:
    return httpx.Response(status, json=body)
