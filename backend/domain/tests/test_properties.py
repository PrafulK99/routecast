import math
from dataclasses import replace
from datetime import datetime, timezone

from hypothesis import given
from hypothesis import strategies as st

from domain.checkpoints import cumulative_totals, place_checkpoints, sample_miles, segment_miles
from domain.models import Route, WeatherSample
from domain.ranking import rank_routes
from domain.risk import assess_risk

from .factories import summary

wind = st.floats(min_value=0, max_value=150, allow_nan=False)
rain = st.floats(min_value=0, max_value=5, allow_nan=False)
snow = st.floats(min_value=0, max_value=10, allow_nan=False)
load = st.integers(min_value=0, max_value=200_000)
increase = st.floats(min_value=0, max_value=100, allow_nan=False)


def level_of(w, r, s, lb):
    return assess_risk(WeatherSample(w, r, s), lb).level


@given(wind, rain, snow, load, increase)
def test_raising_wind_never_lowers_the_level(w, r, s, lb, delta):
    assert level_of(w + delta, r, s, lb) >= level_of(w, r, s, lb)


@given(wind, rain, snow, load, increase)
def test_raising_rain_never_lowers_the_level(w, r, s, lb, delta):
    assert level_of(w, r + delta, s, lb) >= level_of(w, r, s, lb)


@given(wind, rain, snow, load, increase)
def test_raising_snow_never_lowers_the_level(w, r, s, lb, delta):
    assert level_of(w, r, s + delta, lb) >= level_of(w, r, s, lb)


@given(wind, rain, snow, load, st.integers(min_value=0, max_value=200_000))
def test_raising_the_load_never_lowers_the_level(w, r, s, lb, extra):
    assert level_of(w, r, s, lb + extra) >= level_of(w, r, s, lb)


@given(wind, rain, snow, load)
def test_level_is_the_max_of_the_three_individual_levels(w, r, s, lb):
    result = assess_risk(WeatherSample(w, r, s), lb)

    assert result.level == max(result.wind_level, result.rain_level, result.snow_level)


@given(
    total=st.floats(min_value=0.5, max_value=5000, allow_nan=False),
    interval=st.sampled_from([10, 25, 50]),
)
def test_segment_miles_sum_to_the_route_length(total, interval):
    miles = sample_miles(total, interval)
    segments = segment_miles(miles, total)

    assert math.isclose(sum(segments), total, rel_tol=1e-9)
    assert all(segment > 0 for segment in segments)


@given(
    st.lists(st.floats(min_value=0.01, max_value=40, allow_nan=False), min_size=1, max_size=60),
    st.sampled_from([10, 25, 50]),
)
def test_placed_checkpoints_cover_the_whole_route(segment_lengths, interval):
    cum_mi, cum_s = cumulative_totals(segment_lengths, [length * 60 for length in segment_lengths])
    geometry = tuple((0.0, mile / 69.0) for mile in cum_mi)
    route = Route("r", "Route A", geometry, cum_mi, cum_s)
    departure = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

    checkpoints = place_checkpoints(route, interval, departure)

    assert math.isclose(sum(c.segment_mi for c in checkpoints), route.distance_mi, rel_tol=1e-9)
    assert checkpoints[0].mile == 0 and checkpoints[-1].mile == route.distance_mi
    assert [c.eta_utc for c in checkpoints] == sorted(c.eta_utc for c in checkpoints)


route_summaries = st.lists(
    st.builds(
        summary,
        no_travel=st.sampled_from([0.0, 0.0, 5.0, 40.0]),
        severe=st.floats(min_value=0, max_value=100, allow_nan=False),
        high=st.floats(min_value=0, max_value=100, allow_nan=False),
        avg_risk=st.one_of(st.none(), st.floats(min_value=0, max_value=4, allow_nan=False)),
        duration_s=st.floats(min_value=60, max_value=200_000, allow_nan=False),
        distance_mi=st.floats(min_value=1, max_value=3000, allow_nan=False),
    ),
    min_size=1,
    max_size=3,
)


@given(route_summaries, st.randoms(use_true_random=False))
def test_ranking_is_the_same_for_any_input_order(summaries, rng):
    # Unique labels and indices, as the service assigns them.
    routes = [
        replace(s, route_id=f"R{i}", label=f"Route {i}", route_index=i)
        for i, s in enumerate(summaries)
    ]
    shuffled = list(routes)
    rng.shuffle(shuffled)

    assert rank_routes(routes) == rank_routes(shuffled)
