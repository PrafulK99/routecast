from datetime import datetime, timedelta, timezone

import pytest

from domain.checkpoints import (
    choose_interval,
    cumulative_totals,
    eta,
    forecast_hour,
    interpolate_at_mile,
    place_checkpoints,
    sample_miles,
    segment_miles,
)
from domain.models import Route

from .factories import DEPARTURE, straight_route


def test_cumulative_totals_start_at_zero():
    assert cumulative_totals([1.0, 2.0, 3.0], [10, 20, 30]) == (
        (0.0, 1.0, 3.0, 6.0),
        (0.0, 10, 30, 60),
    )


def test_cumulative_totals_reject_mismatched_arrays():
    with pytest.raises(ValueError):
        cumulative_totals([1.0, 2.0], [10])


@pytest.mark.parametrize(
    "total, step, expected",
    [
        (80, 25, [0, 25, 50, 75, 80]),  # the design's example
        (75, 25, [0, 25, 50, 75]),  # destination on a multiple: no duplicate
        (75.0000001, 25, [0, 25, 50, 75.0000001]),  # float noise is not a new checkpoint
        (10, 25, [0, 10]),  # shorter than the interval
        (100, 10, [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
        (0.6, 50, [0, 0.6]),
    ],
)
def test_sample_miles(total, step, expected):
    assert sample_miles(total, step) == pytest.approx(expected)


@pytest.mark.parametrize("total, step", [(0, 25), (-1, 25), (10, 0)])
def test_sample_miles_rejects_non_positive(total, step):
    with pytest.raises(ValueError):
        sample_miles(total, step)


def test_segment_miles_design_example():
    segments = segment_miles([0, 25, 50, 75, 80], 80)

    assert segments == pytest.approx([12.5, 25, 25, 15, 2.5])
    assert sum(segments) == pytest.approx(80)


def test_segment_miles_two_checkpoints_split_the_route():
    assert segment_miles([0, 10], 10) == pytest.approx([5, 5])


@pytest.mark.parametrize(
    "requested, total, expected",
    [
        (10, 1000, 10),  # 101 checkpoints
        (10, 1500, 25),  # 151 at 10 miles, 61 at 25
        (25, 3000, 25),  # 121 checkpoints
        (25, 4000, 50),  # 161 at 25 miles, 81 at 50
        (50, 9000, 50),  # nothing larger exists; stays at 50
    ],
)
def test_choose_interval(requested, total, expected):
    assert choose_interval(total, requested) == expected


def test_choose_interval_honours_a_custom_maximum():
    # 1,000 miles: 101 checkpoints at 10 miles, 41 at 25 miles.
    assert choose_interval(1000, 10) == 10
    assert choose_interval(1000, 10, max_checkpoints=50) == 25
    assert choose_interval(1000, 10, max_checkpoints=30) == 50
    assert choose_interval(1000, 10, max_checkpoints=5) == 50  # still too many: largest returned


def test_choose_interval_rejects_unknown_interval():
    with pytest.raises(ValueError):
        choose_interval(100, 15)


def test_exactly_150_checkpoints_is_allowed():
    # Mile 0, 148 interior marks and the destination make 150; one more mile makes 151.
    assert choose_interval(1490, 10) == 10
    assert choose_interval(1491, 10) == 25


def test_interpolation_between_vertices():
    route = Route(
        "r",
        "Route A",
        ((10.0, 20.0), (12.0, 24.0), (12.0, 28.0)),
        (0.0, 10.0, 30.0),
        (0.0, 100.0, 500.0),
    )

    lat, lon, seconds = interpolate_at_mile(route, 5)
    assert (lat, lon, seconds) == pytest.approx((11.0, 22.0, 50.0))
    lat, lon, seconds = interpolate_at_mile(route, 20)
    assert (lat, lon, seconds) == pytest.approx((12.0, 26.0, 300.0))
    # Exactly on a vertex, and at both ends.
    assert interpolate_at_mile(route, 10) == pytest.approx((12.0, 24.0, 100.0))
    assert interpolate_at_mile(route, 0) == pytest.approx((10.0, 20.0, 0.0))
    assert interpolate_at_mile(route, 30) == pytest.approx((12.0, 28.0, 500.0))


def test_interpolation_survives_a_zero_length_segment():
    route = Route(
        "r", "Route A", ((0.0, 0.0), (1.0, 1.0), (1.0, 1.0), (2.0, 2.0)),
        (0.0, 10.0, 10.0, 20.0), (0.0, 10.0, 10.0, 20.0),
    )  # fmt: skip

    assert interpolate_at_mile(route, 10) == pytest.approx((1.0, 1.0, 10.0))
    assert interpolate_at_mile(route, 15) == pytest.approx((1.5, 1.5, 15.0))


def test_eta_applies_truck_factor():
    assert eta(DEPARTURE, 3600, truck_factor=1.10) == DEPARTURE + timedelta(seconds=3960)
    assert eta(DEPARTURE, 3600, truck_factor=1.0) == DEPARTURE + timedelta(hours=1)


def test_eta_converts_to_utc():
    local = datetime(2026, 11, 2, 7, 0, tzinfo=timezone(timedelta(hours=-5)))

    assert eta(local, 0, 1.0) == DEPARTURE
    assert eta(local, 0, 1.0).utcoffset() == timedelta(0)


def test_naive_datetimes_are_rejected():
    naive = datetime(2026, 11, 2, 12, 0)
    with pytest.raises(ValueError):
        eta(naive, 0)
    with pytest.raises(ValueError):
        forecast_hour(naive)


@pytest.mark.parametrize(
    "minute, second, microsecond, expected_hour",
    [
        (0, 0, 0, 12),
        (20, 0, 0, 12),
        (29, 59, 999999, 12),  # just under half rounds down
        (30, 0, 0, 13),  # half rounds up
        (45, 0, 0, 13),
        (59, 59, 0, 13),
    ],
)
def test_forecast_hour_rounds_to_nearest_hour(minute, second, microsecond, expected_hour):
    eta_utc = datetime(2026, 11, 2, 12, minute, second, microsecond, tzinfo=timezone.utc)

    assert forecast_hour(eta_utc) == datetime(2026, 11, 2, expected_hour, tzinfo=timezone.utc)


def test_forecast_hour_rolls_over_midnight():
    eta_utc = datetime(2026, 11, 2, 23, 40, tzinfo=timezone.utc)

    assert forecast_hour(eta_utc) == datetime(2026, 11, 3, 0, tzinfo=timezone.utc)


def test_departure_at_0020_rounds_each_checkpoint_independently():
    route = straight_route(100, seconds_per_mile=60)
    departure = datetime(2026, 11, 2, 0, 20, tzinfo=timezone.utc)

    checkpoints = place_checkpoints(route, 25, departure, truck_factor=1.0)

    # ETAs: 00:20, 00:45, 01:10, 01:35, 02:00 -> hours 0, 1, 1, 2, 2
    assert [c.forecast_hour_utc.hour for c in checkpoints] == [0, 1, 1, 2, 2]


def test_place_checkpoints_design_example():
    route = straight_route(80, seconds_per_mile=45)

    checkpoints = place_checkpoints(route, 25, DEPARTURE, truck_factor=1.10)

    assert [c.mile for c in checkpoints] == pytest.approx([0, 25, 50, 75, 80])
    assert [c.index for c in checkpoints] == [0, 1, 2, 3, 4]
    assert [c.segment_mi for c in checkpoints] == pytest.approx([12.5, 25, 25, 15, 2.5])
    assert checkpoints[0].eta_utc == DEPARTURE
    # 25 miles x 45 s/mile x 1.10 = 1237.5 s
    assert checkpoints[1].eta_utc == DEPARTURE + timedelta(seconds=1237.5)
    assert checkpoints[-1].lon == pytest.approx(80 / 69.0)
    assert checkpoints[0].lat == 0.0


def test_place_checkpoints_requires_aware_departure():
    with pytest.raises(ValueError):
        place_checkpoints(straight_route(80), 25, datetime(2026, 11, 2, 12, 0))
