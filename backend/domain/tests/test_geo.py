import time

import pytest

from domain.checkpoints import cumulative_totals
from domain.geo import (
    bearing_degrees,
    corridor_points,
    grid_cell,
    haversine_miles,
    offset_point,
    overlap_fraction,
    perpendicular_offsets,
)
from domain.models import Route

from .factories import route_through, straight_route


def north_route(total_miles, route_id="r", lon=-97.0):
    """A route heading north along one meridian, 69 miles per degree of latitude."""
    cum_mi, cum_s = cumulative_totals([total_miles], [total_miles * 60])
    geometry = ((30.0, lon), (30.0 + total_miles / 69.0, lon))
    return Route(route_id, route_id, geometry, cum_mi, cum_s)


@pytest.mark.parametrize(
    "lat, lon, expected",
    [
        (32.7767, -96.7970, (32.8, -96.8)),
        (32.74, -96.74, (32.7, -96.7)),
        (0.04, -0.04, (0.0, 0.0)),
        (-33.86, 151.21, (-33.9, 151.2)),
    ],
)
def test_grid_cell_rounds_to_a_tenth_of_a_degree(lat, lon, expected):
    assert grid_cell(lat, lon) == pytest.approx(expected)


def test_grid_cell_has_no_negative_zero():
    lat, lon = grid_cell(-0.04, -0.04)

    assert str(lat) == "0.0" and str(lon) == "0.0"


def test_nearby_points_share_a_cell():
    assert grid_cell(32.71, -96.69) == grid_cell(32.74, -96.74)
    assert grid_cell(32.71, -96.69) != grid_cell(32.76, -96.69)


def test_corridor_samples_every_spacing_miles():
    points = corridor_points([north_route(100)], spacing_miles=15, cap=200)

    # miles 0, 15, 30, 45, 60, 75, 90 and the end at 100
    assert len(points) == 8
    assert points[0] == pytest.approx((30.0, -97.0))
    assert points[-1] == pytest.approx((30.0 + 100 / 69.0, -97.0))


def test_route_shorter_than_spacing_yields_start_and_end():
    points = corridor_points([north_route(6)], spacing_miles=15, cap=200)

    assert len(points) == 2
    assert points[0] == pytest.approx((30.0, -97.0))
    assert points[1] == pytest.approx((30.0 + 6 / 69.0, -97.0))


def test_points_in_an_already_used_cell_are_dropped():
    # Two copies of the same route: every point of the second is a duplicate.
    one = corridor_points([north_route(100)], spacing_miles=15, cap=200)
    two = corridor_points([north_route(100, "a"), north_route(100, "b")], spacing_miles=15, cap=200)

    assert two == one


def test_distinct_corridors_keep_their_own_points():
    west = north_route(100, "w", lon=-98.0)
    east = north_route(100, "e", lon=-96.0)

    points = corridor_points([west, east], spacing_miles=15, cap=200)

    assert len(points) == 16
    assert len({grid_cell(*p) for p in points}) == 16


def test_spacing_grows_until_the_result_fits_the_cap():
    route = north_route(1500)  # 15-mile spacing would give 101 points

    points = corridor_points([route], spacing_miles=15, cap=40)

    assert 2 <= len(points) <= 40
    assert points[0] == pytest.approx((30.0, -97.0))


def test_default_cap_is_200():
    # 5000 miles at 15 miles is 335 distinct cells; the default cap forces it down.
    points = corridor_points([straight_route(5000, vertices=2)])

    assert len(points) <= 200


def test_unreachable_cap_truncates_instead_of_looping():
    points = corridor_points([north_route(100)], spacing_miles=15, cap=1)

    assert len(points) == 1


def test_haversine_known_distances():
    assert haversine_miles((0, 0), (0, 1)) == pytest.approx(69.09, abs=0.05)
    assert haversine_miles((32.7767, -96.7970), (41.8781, -87.6298)) == pytest.approx(802, rel=0.01)
    assert haversine_miles((10, 20), (10, 20)) == 0


@pytest.mark.parametrize(
    "target, expected",
    [((1, 0), 0), ((0, 1), 90), ((-1, 0), 180), ((0, -1), 270)],
)
def test_bearing_points_of_the_compass(target, expected):
    assert bearing_degrees((0, 0), target) == pytest.approx(expected)


@pytest.mark.parametrize("bearing", [0, 37, 90, 181, 270, 359])
def test_offset_point_round_trips_distance_and_bearing(bearing):
    start = (32.0, -97.0)

    moved = offset_point(start, bearing, 30)

    assert haversine_miles(start, moved) == pytest.approx(30, abs=1e-6)
    assert bearing_degrees(start, moved) == pytest.approx(bearing, abs=0.2)


def test_offset_point_longitude_wraps_into_range():
    _, lon = offset_point((0.0, 179.9), 90, 50)

    assert -180 <= lon < 180


def test_perpendicular_offsets_sit_left_and_right_of_a_northbound_route():
    route = north_route(100)

    left, right = perpendicular_offsets(route, 0.35, 20)

    middle = (30.0 + 35 / 69.0, -97.0)
    assert left[1] < -97.0 < right[1]  # heading north: left is west, right is east
    assert haversine_miles(left, middle) == pytest.approx(20, abs=0.1)
    assert haversine_miles(right, middle) == pytest.approx(20, abs=0.1)
    assert left[0] == pytest.approx(middle[0], abs=0.01)


def test_perpendicular_offsets_swap_sides_when_the_route_reverses():
    southbound = route_through([(31.5, -97.0), (30.0, -97.0)])

    left, right = perpendicular_offsets(southbound, 0.5, 10)

    assert right[1] < -97.0 < left[1]


def test_overlap_of_identical_routes_is_one():
    route = north_route(100)

    assert overlap_fraction(route, route, 5, 1) == 1.0


def test_overlap_of_distant_routes_is_zero():
    assert overlap_fraction(north_route(100), north_route(100, lon=-96.7), 5, 1) == 0.0


def test_overlap_is_the_shared_part_of_the_first_route():
    a = north_route(100)
    # b follows a for 50 miles, then veers east.
    b = route_through([(30.0, -97.0), (30.0 + 50 / 69.0, -97.0), (30.0 + 60 / 69.0, -95.0)])

    # a's samples at miles 0, 5, ..., 50 are shared: 11 of 21.
    assert overlap_fraction(a, b, 5, 1) == pytest.approx(11 / 21)


def test_overlap_tolerance_edge():
    a = north_route(100)
    degrees_per_mile = 1 / 69.0 / 0.7  # longitude degrees per mile at this latitude, roughly
    close = route_through([(30.0, -97.0 + 0.5 * degrees_per_mile), (30.0 + 100 / 69.0, -97.0 + 0.5 * degrees_per_mile)])
    apart = route_through([(30.0, -97.0 + 1.5 * degrees_per_mile), (30.0 + 100 / 69.0, -97.0 + 1.5 * degrees_per_mile)])

    assert overlap_fraction(a, close, 5, 1) == 1.0
    assert overlap_fraction(a, apart, 5, 1) == 0.0


def test_overlap_is_fast_on_dense_geometry():
    # 700 miles with 12,000 vertices, like a real Mapbox route.
    def dense(lon):
        return route_through([(30.0 + i * 10.0 / 12000, lon) for i in range(12001)])

    a, b = dense(-97.0), dense(-97.001)
    started = time.perf_counter()

    assert overlap_fraction(a, b, 5, 1) == 1.0
    assert time.perf_counter() - started < 5
