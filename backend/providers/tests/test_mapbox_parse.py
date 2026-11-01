import pytest

from providers.constants import METERS_PER_MILE
from providers.errors import NoRouteError, RoutingUnavailableError
from providers.interfaces import WARNING_MISSING_ANNOTATIONS
from providers.mapbox import parse_directions

from .helpers import directions_body, mapbox_body


def test_parses_the_recorded_two_route_response():
    body = mapbox_body()

    routes, warnings = parse_directions(body)

    assert warnings == []
    assert [(r.id, r.label) for r in routes] == [("route-1", "Route A"), ("route-2", "Route B")]
    for route, raw in zip(routes, body["routes"]):
        vertices = len(raw["geometry"]["coordinates"])
        assert len(route.geometry) == len(route.cumulative_mi) == len(route.cumulative_s) == vertices
        assert route.cumulative_mi[0] == 0 and route.cumulative_s[0] == 0
        # Meters become miles with 1 mile = 1609.344 m.
        assert route.distance_mi == pytest.approx(raw["distance"] / METERS_PER_MILE, rel=0.005)
        assert route.duration_s == pytest.approx(raw["duration"], rel=0.005)


def test_geometry_is_lat_lon_not_lon_lat():
    routes, _ = parse_directions(mapbox_body())

    lat, lon = routes[0].geometry[0]
    # Kansas City to St. Louis: latitude near 39, longitude near -94.6.
    assert 38 < lat < 40 and -96 < lon < -93


def test_cumulative_arrays_never_decrease():
    routes, _ = parse_directions(mapbox_body())

    for route in routes:
        assert list(route.cumulative_mi) == sorted(route.cumulative_mi)
        assert list(route.cumulative_s) == sorted(route.cumulative_s)


def test_per_segment_values_come_from_the_annotations():
    body = mapbox_body()
    annotation = body["routes"][0]["legs"][0]["annotation"]

    route = parse_directions(body)[0][0]

    assert route.cumulative_mi[1] == pytest.approx(annotation["distance"][0] / METERS_PER_MILE)
    assert route.cumulative_s[1] == pytest.approx(annotation["duration"][0])
    assert route.cumulative_s[-1] == pytest.approx(sum(annotation["duration"]))


def test_annotations_of_several_legs_are_joined():
    body = directions_body(
        [[[(30.0, -97.0), (30.5, -97.0), (31.0, -97.0)], [(31.0, -97.0), (31.5, -97.0), (32.0, -97.0)]]]
    )

    routes, warnings = parse_directions(body)

    assert warnings == []
    assert len(routes[0].geometry) == 5
    assert routes[0].distance_mi == pytest.approx(body["routes"][0]["distance"] / METERS_PER_MILE)


def assert_proportional(route, raw):
    assert route.distance_mi == pytest.approx(raw["distance"] / METERS_PER_MILE)
    assert route.duration_s == pytest.approx(raw["duration"])
    assert list(route.cumulative_mi) == sorted(route.cumulative_mi)
    assert len(route.cumulative_mi) == len(route.geometry)


def test_missing_annotations_fall_back_to_proportional_time_with_a_warning():
    body = mapbox_body()
    del body["routes"][0]["legs"][0]["annotation"]

    routes, warnings = parse_directions(body)

    assert warnings == [WARNING_MISSING_ANNOTATIONS]
    assert_proportional(routes[0], body["routes"][0])
    # The other route still uses its real annotations.
    assert routes[1].distance_mi == pytest.approx(
        sum(body["routes"][1]["legs"][0]["annotation"]["distance"]) / METERS_PER_MILE
    )


@pytest.mark.parametrize("key", ["distance", "duration"])
def test_annotation_of_the_wrong_length_falls_back(key):
    body = mapbox_body()
    body["routes"][0]["legs"][0]["annotation"][key].pop()

    routes, warnings = parse_directions(body)

    assert warnings == [WARNING_MISSING_ANNOTATIONS]
    assert_proportional(routes[0], body["routes"][0])


def test_null_inside_an_annotation_falls_back():
    body = mapbox_body()
    body["routes"][0]["legs"][0]["annotation"]["duration"][10] = None

    routes, warnings = parse_directions(body)

    assert warnings == [WARNING_MISSING_ANNOTATIONS]
    assert_proportional(routes[0], body["routes"][0])


def test_the_warning_is_reported_once_for_several_routes():
    body = mapbox_body()
    for raw in body["routes"]:
        del raw["legs"][0]["annotation"]

    assert parse_directions(body)[1] == [WARNING_MISSING_ANNOTATIONS]


@pytest.mark.parametrize("code", ["NoRoute", "NoSegment"])
def test_no_route_codes_raise_no_route(code):
    with pytest.raises(NoRouteError):
        parse_directions({"code": code, "routes": []})


def test_ok_without_routes_raises_no_route():
    with pytest.raises(NoRouteError):
        parse_directions({"code": "Ok", "routes": []})


def test_other_codes_are_a_routing_failure():
    with pytest.raises(RoutingUnavailableError):
        parse_directions({"code": "InvalidInput", "message": "bad"})
