"""Every validation rule of both POST endpoints, at and beyond its boundary."""

import copy

import pytest

from .helpers import analyze_payload, heatmap_payload

ANALYZE, HEATMAP = "/api/analyze", "/api/heatmap"
MILE = 1 / 69.09  # degrees of latitude per mile; the frozen clock is 2026-11-02 12:30 UTC


def with_value(payload, path, value):
    """A copy of the payload with the value at a dotted path replaced (or removed with `...`)."""
    payload = copy.deepcopy(payload)
    *parents, last = path.split(".")
    target = payload
    for key in parents:
        target = target[int(key)] if isinstance(target, list) else target[key]
    if value is ...:
        del target[last]
    elif isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value
    return payload


def invalid_field(client, url, payload):
    response = client.post(url, payload, format="json")
    assert response.status_code == 400, response.content
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    return error["fields"]


def accepted(client, url, payload):
    response = client.post(url, payload, format="json")
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture(autouse=True)
def default_providers(providers):
    providers()


BASE = analyze_payload()

# --- coordinates ---------------------------------------------------------------

BAD_COORDINATES = [
    ("origin.lat", 90.0001), ("origin.lat", -90.0001), ("origin.lon", 180.0001),
    ("origin.lon", -180.0001), ("destination.lat", 91), ("destination.lon", -181),
    ("origin.lat", "north"), ("origin.lat", "nan"), ("origin.lon", "inf"), ("origin.lat", None),
    ("origin.lat", True), ("origin.lat", ...), ("origin", ...), ("destination", ...),
]


@pytest.mark.parametrize("path, value", BAD_COORDINATES)
def test_bad_coordinates_are_rejected(client, path, value):
    fields = invalid_field(client, ANALYZE, with_value(BASE, path, value))

    assert path in fields


@pytest.mark.parametrize(
    "origin, destination",
    [
        ({"lat": 90, "lon": 0}, {"lat": 0, "lon": 0}),
        ({"lat": -90, "lon": 0}, {"lat": 0, "lon": 0}),
        ({"lat": 0, "lon": 180}, {"lat": 0, "lon": 90}),
        ({"lat": 0, "lon": -180}, {"lat": 0, "lon": -90}),
    ],
)
def test_coordinates_on_the_boundary_are_accepted(client, origin, destination):
    accepted(client, ANALYZE, {**BASE, "origin": origin, "destination": destination})


def test_the_label_is_optional(client):
    accepted(client, ANALYZE, with_value(BASE, "origin.label", ...))


# --- origin and destination at least 0.5 mile apart -----------------------------


@pytest.mark.parametrize("miles, ok", [(0.0, False), (0.4, False), (0.49, False), (0.6, True), (5.0, True)])
def test_origin_and_destination_must_be_half_a_mile_apart(client, miles, ok):
    payload = with_value(BASE, "destination", {"lat": 30.0 + miles * MILE, "lon": -100.0})
    payload["origin"] = {"lat": 30.0, "lon": -100.0}

    if ok:
        accepted(client, ANALYZE, payload)
    else:
        assert "destination" in invalid_field(client, ANALYZE, payload)


# --- departure window -----------------------------------------------------------

BAD_DEPARTURES = [
    "2026-11-02T14:00:00",  # no UTC offset
    "2026-11-02 14:00",
    "tomorrow",
    "",
    "2026-11-02T11:59:59Z",  # before the current hour (12:00)
    "2026-11-01T14:00:00Z",
    "2026-11-09T12:30:01Z",  # one second past 7 days from now
    "2026-12-01T00:00:00Z",
    1_793_000_000,
    None,
]


@pytest.mark.parametrize("value", BAD_DEPARTURES)
def test_bad_departures_are_rejected(client, value):
    assert "departure_time" in invalid_field(client, ANALYZE, with_value(BASE, "departure_time", value))


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-02T12:00:00Z",  # exactly the start of the current hour
        "2026-11-02T12:00:00+00:00",
        "2026-11-02T09:00:00-03:00",  # offsets are converted
        "2026-11-05T08:15:00Z",
        "2026-11-09T12:30:00Z",  # exactly 7 days from now
    ],
)
def test_departures_inside_the_window_are_accepted(client, value):
    body = accepted(client, ANALYZE, with_value(BASE, "departure_time", value))

    assert body["routes"]


def test_the_departure_error_names_the_allowed_window(client):
    message = invalid_field(client, ANALYZE, with_value(BASE, "departure_time", "2026-11-01T00:00:00Z"))[
        "departure_time"
    ][0]

    assert "2026-11-02 12:00 UTC" in message and "2026-11-09 12:30 UTC" in message


def test_a_naive_departure_asks_for_an_offset(client):
    message = invalid_field(client, ANALYZE, with_value(BASE, "departure_time", "2026-11-02T14:00:00"))[
        "departure_time"
    ][0]

    assert "UTC offset" in message


# --- load weight ---------------------------------------------------------------


@pytest.mark.parametrize("value", [-1, 200_001, 1.5, "heavy", None, True, ...])
def test_bad_load_weights_are_rejected(client, value):
    assert "load_weight_lb" in invalid_field(client, ANALYZE, with_value(BASE, "load_weight_lb", value))


@pytest.mark.parametrize("value", [0, 1, 30_000, 40_000, 200_000, 10_000.0])
def test_load_weights_in_range_are_accepted(client, value):
    accepted(client, ANALYZE, with_value(BASE, "load_weight_lb", value))


# --- checkpoint interval -------------------------------------------------------


@pytest.mark.parametrize("value", [0, 5, 15, 100, "far", None])
def test_other_intervals_are_rejected(client, value):
    assert "checkpoint_interval_miles" in invalid_field(
        client, ANALYZE, with_value(BASE, "checkpoint_interval_miles", value)
    )


@pytest.mark.parametrize("value", [10, 25, 50])
def test_allowed_intervals_are_used(client, value):
    body = accepted(client, ANALYZE, with_value(BASE, "checkpoint_interval_miles", value))

    assert body["meta"]["interval_miles"] == value


def test_the_interval_defaults_to_25(client):
    assert accepted(client, ANALYZE, BASE)["meta"]["interval_miles"] == 25


# --- heatmap ---------------------------------------------------------------------

HEAT = heatmap_payload()


def test_heatmap_accepts_up_to_120_points(client):
    points = [[30.0 + 0.1 * i, -99.0] for i in range(120)]

    assert len(accepted(client, HEATMAP, with_value(HEAT, "points", points))["points"]) == 120


def test_heatmap_rejects_121_points(client):
    points = [[30.0 + 0.1 * i, -99.0] for i in range(121)]

    assert "points" in invalid_field(client, HEATMAP, with_value(HEAT, "points", points))


@pytest.mark.parametrize(
    "path, value",
    [
        ("points", []),
        ("points", "30,-99"),
        ("points", None),
        ("points", ...),
        ("points.0", [30.0]),
        ("points.0", [30.0, -99.0, 5.0]),
        ("points.0", [91, 0]),
        ("points.0", [0, 181]),
        ("points.0", ["x", 0]),
        ("points.0", [30.0, "nan"]),
        ("points.0", "30,-99"),
        ("departure_time", "2026-11-02T14:00:00"),
        ("departure_time", "2026-11-02T11:00:00Z"),
        ("departure_time", "2026-11-10T00:00:00Z"),
        ("load_weight_lb", -5),
        ("load_weight_lb", 200_001),
    ],
)
def test_heatmap_rejects_bad_input(client, path, value):
    fields = invalid_field(client, HEATMAP, with_value(HEAT, path, value))

    assert any(key == path or key.startswith(path + ".") for key in fields), fields


def test_heatmap_boundary_values_are_accepted(client):
    payload = with_value(HEAT, "points", [[90, 180], [-90, -180]])
    payload = with_value(payload, "load_weight_lb", 200_000)

    accepted(client, HEATMAP, payload)
