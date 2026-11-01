import pytest

from domain.checkpoints import cumulative_totals
from domain.geo import corridor_points, grid_cell
from domain.models import Route

from .factories import straight_route


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
