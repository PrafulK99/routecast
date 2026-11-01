import pytest

from domain.checkpoints import place_checkpoints
from domain.constants import Level
from domain.models import WeatherSample
from domain.risk import assess_risk
from domain.scoring import summarize_route

from .factories import DEPARTURE, straight_route

# The design's example: 80 miles, interval 25 -> segments 12.5, 25, 25, 15, 2.5.
ROUTE = straight_route(80, seconds_per_mile=45)
CHECKPOINTS = place_checkpoints(ROUTE, 25, DEPARTURE)


def risks_for(*winds, load=0):
    return [assess_risk(WeatherSample(w, 0, 0) if w is not None else None, load) for w in winds]


def test_miles_by_level_and_average_risk():
    # Levels: Low, Moderate, High, Severe, Low
    summary = summarize_route(ROUTE, 0, CHECKPOINTS, risks_for(10, 30, 40, 50, 10))

    assert summary.miles_by_level == pytest.approx(
        {
            Level.LOW: 12.5 + 2.5,
            Level.MODERATE: 25,
            Level.HIGH: 25,
            Level.SEVERE: 15,
            Level.NO_TRAVEL: 0,
        }
    )
    assert sum(summary.miles_by_level.values()) == pytest.approx(80)
    # (0*15 + 1*25 + 2*25 + 3*15) / 80
    assert summary.avg_risk == pytest.approx(120 / 80)
    assert summary.worst_level == Level.SEVERE
    assert summary.coverage_pct == pytest.approx(100)
    assert summary.blocked is False


def test_duration_is_truck_adjusted():
    summary = summarize_route(ROUTE, 0, CHECKPOINTS, risks_for(10, 10, 10, 10, 10), truck_factor=1.10)

    assert summary.duration_s == pytest.approx(80 * 45 * 1.10)
    assert summary.distance_mi == pytest.approx(80)


def test_no_travel_miles_set_the_blocked_flag():
    summary = summarize_route(ROUTE, 0, CHECKPOINTS, risks_for(10, 60, 10, 10, 10))

    assert summary.blocked is True
    assert summary.miles_by_level[Level.NO_TRAVEL] == pytest.approx(25)
    assert summary.worst_level == Level.NO_TRAVEL


def test_unavailable_checkpoints_are_excluded_and_lower_coverage():
    # The middle checkpoint (25 miles) has no forecast.
    summary = summarize_route(ROUTE, 0, CHECKPOINTS, risks_for(10, 30, None, 50, 10))

    assert sum(summary.miles_by_level.values()) == pytest.approx(55)
    assert summary.coverage_pct == pytest.approx(55 / 80 * 100)
    # (1*25 + 3*15) / 55: the unknown stretch is not averaged in as Low
    assert summary.avg_risk == pytest.approx(70 / 55)


def test_partial_checkpoints_count_as_scored():
    risks = risks_for(10, 10, 10, 10, 10)
    risks[2] = assess_risk(WeatherSample(wind_mph=47), 0)

    summary = summarize_route(ROUTE, 0, CHECKPOINTS, risks)

    assert summary.coverage_pct == pytest.approx(100)
    assert summary.miles_by_level[Level.SEVERE] == pytest.approx(25)


def test_no_scored_miles_has_no_average_and_zero_coverage():
    summary = summarize_route(ROUTE, 0, CHECKPOINTS, risks_for(None, None, None, None, None))

    assert summary.avg_risk is None
    assert summary.worst_level is None
    assert summary.coverage_pct == 0
    assert summary.blocked is False


def test_risk_count_must_match_checkpoints():
    with pytest.raises(ValueError):
        summarize_route(ROUTE, 0, CHECKPOINTS, risks_for(10, 10))


def test_route_index_label_and_id_are_carried_over():
    summary = summarize_route(ROUTE, 2, CHECKPOINTS, risks_for(10, 10, 10, 10, 10))

    assert (summary.route_id, summary.label, summary.route_index) == ("r", "Route A", 2)
