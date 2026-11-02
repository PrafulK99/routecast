"""Weather supplied by the browser: same results as the server fetch, strict validation, never Low."""

import copy
import json
from datetime import timedelta

import pytest
from django.core.cache import cache

from api.weather_payload import MAX_WEATHER_HOURS, max_cells

from .helpers import (
    DEPARTURE,
    ScenarioWeather,
    analyze_payload,
    calm,
    heatmap_payload,
    storm_on_route_a,
    three_routes,
    two_routes,
    uniform,
    wind,
)

HOUR_FORMAT = "%Y-%m-%dT%H:00"
ARRAYS = ("wind_speed_10m", "rain", "showers", "snowfall")


def post(client, url, payload):
    return client.post(url, payload, format="json")


def weather_payload(client, scenario, **overrides):
    """What the browser would send: the scenario's data for the cells and window /api/plan names."""
    plan = post(client, "/api/plan", analyze_payload(**overrides)).json()
    return entries_for(scenario, plan["cells"], plan["window"])


def entries_for(scenario, cells, window=None):
    """Weather entries for exact cells, trimmed to the window (default: departure to +48 hours)."""
    first = DEPARTURE.replace(hour=int(window["first_hour"][11:13])) if window else DEPARTURE
    last = DEPARTURE + timedelta(hours=48)
    cells = [tuple(cell) for cell in cells]
    entries = []
    for (lat, lon), series in scenario.get_series(cells, last).series.items():
        hours = sorted(hour for hour in series if first <= hour <= last)
        samples = [series[hour] for hour in hours]
        entries.append(
            {
                "lat": lat,
                "lon": lon,
                "time": [hour.strftime(HOUR_FORMAT) for hour in hours],
                "wind_speed_10m": [s.wind_mph for s in samples],
                "rain": [s.rain_in_hr for s in samples],
                "showers": [None if s.rain_in_hr is None else 0.0 for s in samples],
                "snowfall": [s.snow_in_hr for s in samples],
            }
        )
    return entries


SCENARIOS = {
    "calm": (three_routes, lambda: ScenarioWeather(calm), {}),
    "heavy load in wind": (two_routes, lambda: ScenarioWeather(uniform(wind(40.0))), {"load_weight_lb": 45_000}),
    "storm on route A": (two_routes, lambda: ScenarioWeather(storm_on_route_a), {}),
    "no travel everywhere": (three_routes, lambda: ScenarioWeather(uniform(wind(60.0))), {}),
    "forecast gap": (two_routes, lambda: ScenarioWeather(calm, until=DEPARTURE + timedelta(hours=2)), {}),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_supplied_weather_gives_the_same_analysis_as_the_server_fetch(client, providers, name):
    routing, make_weather, overrides = SCENARIOS[name]
    server_weather = make_weather()
    providers(routing(), server_weather)
    expected = post(client, "/api/analyze", analyze_payload(**overrides)).json()
    assert server_weather.calls  # the server-fetch path asked its provider

    unused = make_weather()
    providers(routing(), unused)
    entries = weather_payload(client, make_weather(), **overrides)
    response = post(client, "/api/analyze", analyze_payload(weather=entries, **overrides))

    assert response.status_code == 200, response.json()
    assert response.json() == expected
    assert unused.calls == []  # no server-side Open-Meteo call


def test_supplied_weather_gives_the_same_heatmap_as_the_server_fetch(client, providers):
    providers(two_routes(), ScenarioWeather(storm_on_route_a))
    analysis = post(client, "/api/analyze", analyze_payload()).json()
    points = analysis["corridor_points"]
    expected = post(client, "/api/heatmap", heatmap_payload(points=points)).json()

    entries = entries_for(ScenarioWeather(storm_on_route_a), analysis["corridor_cells"])  # the exact cells named
    unused = ScenarioWeather(storm_on_route_a)
    providers(two_routes(), unused)
    response = post(client, "/api/heatmap", heatmap_payload(points=points, weather=entries))

    assert len(entries) == len(analysis["corridor_cells"])
    assert response.status_code == 200, response.json()
    assert response.json() == expected
    assert unused.calls == []


def supplied_run(client, providers, edit=None):
    """Analyze with the storm scenario's weather after `edit(entries)` changed it."""
    providers(two_routes(), ScenarioWeather(storm_on_route_a))
    entries = weather_payload(client, ScenarioWeather(storm_on_route_a))
    if edit:
        edit(entries)
    return post(client, "/api/analyze", analyze_payload(weather=entries)), entries


def test_a_missing_cell_makes_its_checkpoints_unavailable_with_a_warning(client, providers):
    response, _ = supplied_run(client, providers, lambda entries: entries.pop(0))
    body = response.json()

    assert response.status_code == 200
    assert any("could not be fetched for 1 location(s)" in w for w in body["meta"]["warnings"])
    unavailable = [cp for r in body["routes"] for cp in r["checkpoints"] if cp["status"] == "unavailable"]
    assert unavailable
    # Never a Low rating where the answer is unknown.
    assert all(cp["risk"]["level"] is None and cp["wind_mph"] is None for cp in unavailable)


def test_missing_hours_make_checkpoints_unavailable(client, providers):
    def keep_two_hours(entries):
        for entry in entries:
            for key in ("time", *ARRAYS):
                entry[key] = entry[key][:2]

    body = supplied_run(client, providers, keep_two_hours)[0].json()

    assert any(cp["status"] == "unavailable" for r in body["routes"] for cp in r["checkpoints"])
    assert all(r["summary"]["coverage_pct"] < 100 for r in body["routes"])


def test_nulls_leave_a_value_unknown_not_zero(client, providers):
    def null_everything(entries):
        for entry in entries:
            for key in ARRAYS:
                entry[key] = [None] * len(entry[key])

    body = supplied_run(client, providers, null_everything)[0].json()

    assert all(cp["status"] == "unavailable" for r in body["routes"] for cp in r["checkpoints"])


def test_no_cell_matching_any_checkpoint_is_weather_unavailable(client, providers):
    def move_away(entries):
        for entry in entries:
            entry["lat"] += 10.0

    response, _ = supplied_run(client, providers, move_away)

    assert response.status_code == 502 and response.json()["error"]["code"] == "weather_unavailable"


def test_an_empty_list_is_weather_unavailable_not_an_all_low_result(client, providers):
    providers(two_routes(), ScenarioWeather(calm))

    response = post(client, "/api/analyze", analyze_payload(weather=[]))

    assert response.status_code == 502 and response.json()["error"]["code"] == "weather_unavailable"


def test_cells_nobody_needs_are_ignored(client, providers):
    def add_extra(entries):
        extra = copy.deepcopy(entries[0])
        extra["lat"], extra["lon"] = 10.0, 10.0
        entries.append(extra)

    expected = supplied_run(client, providers)[0].json()

    assert supplied_run(client, providers, add_extra)[0].json() == expected


def test_null_or_absent_weather_uses_the_server_fetch(client, providers):
    _, weather = providers(two_routes(), ScenarioWeather(calm))

    post(client, "/api/analyze", analyze_payload())
    post(client, "/api/analyze", analyze_payload(weather=None))

    assert len(weather.calls) == 2


def test_supplied_weather_is_never_cached_for_anyone_else(client, providers):
    _, entries = supplied_run(client, providers)

    assert [cache.get(f"weather:{e['lat']:.1f}:{e['lon']:.1f}") for e in entries] == [None] * len(entries)


# --- validation ---------------------------------------------------------------------


def entry(lat=30.0, lon=-99.0, hours=3):
    return {
        "lat": lat,
        "lon": lon,
        "time": [(DEPARTURE + timedelta(hours=h)).strftime(HOUR_FORMAT) for h in range(hours)],
        "wind_speed_10m": [5.0] * hours,
        "rain": [0.0] * hours,
        "showers": [0.0] * hours,
        "snowfall": [0.0] * hours,
    }


def with_(base, **changes):
    return {**copy.deepcopy(base), **changes}


def without(base, key):
    return {k: v for k, v in copy.deepcopy(base).items() if k != key}


def three_times(*texts):
    return list(texts)


BAD_WEATHER = {
    "not a list": ({"lat": 1}, "must be a list"),
    "entry not an object": ([[1, 2]], "must be an object"),
    "missing key": ([without(entry(), "rain")], "exactly these keys"),
    "extra key": ([with_(entry(), elevation=3)], "exactly these keys"),
    "lat not a number": ([with_(entry(), lat="30")], "finite numbers"),
    "lat is a bool": ([with_(entry(), lat=True)], "finite numbers"),
    "lat out of range": ([with_(entry(), lat=91.0)], "out of range"),
    "lon out of range": ([with_(entry(), lon=-181.0)], "out of range"),
    "no hours": ([entry(hours=0)], "1 to 400"),
    "time not a list": ([with_(entry(), time="2026-11-02T14:00")], "1 to 400"),
    "time with zone suffix": ([with_(entry(), time=["2026-11-02T14:00Z"] * 3)], "no zone suffix"),
    "time with offset": ([with_(entry(), time=["2026-11-02T14:00+00:00"] * 3)], "no zone suffix"),
    "time with minutes": (
        [with_(entry(), time=["2026-11-02T14:30", "2026-11-02T15:30", "2026-11-02T16:30"])],
        "UTC hour",
    ),
    "time not a real date": (
        [with_(entry(), time=["2026-13-02T14:00", "2026-13-02T15:00", "2026-13-02T16:00"])],
        "not a real date",
    ),
    "time not text": ([with_(entry(), time=[1, 2, 3])], "UTC hour"),
    "time unsorted": (
        [with_(entry(), time=["2026-11-02T15:00", "2026-11-02T14:00", "2026-11-02T16:00"])],
        "increasing",
    ),
    "time repeated": ([with_(entry(), time=["2026-11-02T14:00"] * 3)], "increasing"),
    "array too short": ([with_(entry(), rain=[0.0, 0.0])], "one value per hour"),
    "array too long": ([with_(entry(), snowfall=[0.0] * 4)], "one value per hour"),
    "array not a list": ([with_(entry(), showers=0.0)], "one value per hour"),
    "negative value": ([with_(entry(), wind_speed_10m=[5.0, -0.1, 5.0])], "wind_speed_10m[1]"),
    "string value": ([with_(entry(), rain=[0.0, "0.1", 0.0])], "rain[1]"),
    "bool value": ([with_(entry(), snowfall=[0.0, True, 0.0])], "snowfall[1]"),
    "two entries for one cell": ([entry(), entry(lat=30.04, lon=-99.04)], "same 0.1 degree grid cell"),
    "too many hours": ([entry(hours=MAX_WEATHER_HOURS + 1)], "1 to 400"),
}


@pytest.mark.parametrize("name", BAD_WEATHER)
def test_invalid_weather_is_a_validation_error_on_both_endpoints(client, providers, name):
    weather, fragment = BAD_WEATHER[name]
    providers(two_routes(), ScenarioWeather(calm))

    for url, payload in (
        ("/api/analyze", analyze_payload(weather=weather)),
        ("/api/heatmap", heatmap_payload(weather=weather)),
    ):
        response = post(client, url, payload)
        assert response.status_code == 400, (url, response.json())
        messages = " ".join(response.json()["error"]["fields"].get("weather", []))
        assert fragment in messages, messages


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected(client, providers, token):
    providers(two_routes(), ScenarioWeather(calm))
    bad = with_(entry(), wind_speed_10m=[5.0, float("nan"), 5.0])
    text = json.dumps(analyze_payload(weather=[bad])).replace("NaN", token)

    response = client.post("/api/analyze", text, content_type="application/json")

    assert response.status_code == 400


def many_cells(count, hours=1):
    """`count` entries in distinct grid cells, far from the test routes."""
    return [entry(lat=-60.0 + 0.1 * (i // 100), lon=-100.0 + 0.1 * (i % 100), hours=hours) for i in range(count)]


def test_the_cell_limit_is_450_three_routes_of_150_checkpoints(client, providers):
    assert max_cells() == 450
    providers(two_routes(), ScenarioWeather(calm))

    at_limit = post(client, "/api/analyze", analyze_payload(weather=many_cells(450)))
    over = post(client, "/api/analyze", analyze_payload(weather=many_cells(451)))

    assert at_limit.status_code == 502  # valid, but none of these cells is on the route
    assert over.status_code == 400 and "at most 450" in " ".join(over.json()["error"]["fields"]["weather"])


def test_the_hour_limit_is_400(client, providers):
    providers(two_routes(), ScenarioWeather(calm))

    at_limit = post(client, "/api/analyze", analyze_payload(weather=[entry(hours=400)]))
    over = post(client, "/api/analyze", analyze_payload(weather=[entry(hours=401)]))

    assert at_limit.status_code == 502  # accepted; the cell is not on the route
    assert over.status_code == 400


def test_the_largest_honest_payload_fits_the_request_limit(client, providers):
    # 450 cells x 200 hours with realistic numbers: the longest trip the server accepts.
    providers(two_routes(), ScenarioWeather(calm))
    times = [(DEPARTURE + timedelta(hours=h)).strftime(HOUR_FORMAT) for h in range(200)]
    big = [
        with_(
            cell, time=times, wind_speed_10m=[12.3] * 200, rain=[0.004] * 200, showers=[0.001] * 200,
            snowfall=[0.012] * 200,
        )  # fmt: skip
        for cell in many_cells(450)
    ]
    payload = analyze_payload(weather=big)

    response = post(client, "/api/analyze", payload)

    assert 3_000_000 < len(json.dumps(payload)) < 5 * 1024 * 1024
    assert response.status_code == 502  # accepted and validated; no cell is on the route


def test_a_body_over_the_limit_is_413_in_the_standard_error_shape(client, providers, settings):
    providers(two_routes(), ScenarioWeather(calm))
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 1000

    response = post(client, "/api/analyze", analyze_payload(weather=[entry(hours=40)]))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response["X-Request-ID"]
