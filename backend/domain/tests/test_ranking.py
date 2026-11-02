import pytest

from domain.ranking import rank_routes

from .factories import summary


def winner_of(*summaries):
    return rank_routes(list(summaries)).route_id


# Each key decides when every key before it is equal.
@pytest.mark.parametrize(
    "better, worse",
    [
        (dict(no_travel=0, severe=50), dict(no_travel=1, severe=0)),  # decision 12
        (dict(severe=0, high=90), dict(severe=1, high=0)),
        (dict(high=10, avg_risk=2.0), dict(high=11, avg_risk=0.1)),
        (dict(avg_risk=0.4, duration_s=9000), dict(avg_risk=0.5, duration_s=1000)),
        (dict(duration_s=1000), dict(duration_s=1001)),
    ],
    ids=["no_travel", "severe", "high", "avg_risk", "duration"],
)
def test_each_key_decides_in_strict_order(better, worse):
    a = summary("Route A", 0, **worse)
    b = summary("Route B", 1, **better)

    assert winner_of(a, b) == "Route B"
    assert winner_of(b, a) == "Route B"


def test_miles_are_compared_to_a_tenth_of_a_mile():
    # 0.04 and 0.0 round to the same 0.0, so the next key (duration) decides.
    a = summary("Route A", 0, severe=0.04, duration_s=2000)
    b = summary("Route B", 1, severe=0.0, duration_s=1000)
    c = summary("Route C", 2, severe=0.06, duration_s=500)  # rounds to 0.1: loses

    assert winner_of(a, b, c) == "Route B"


def test_average_risk_is_compared_to_three_decimals():
    a = summary("Route A", 0, avg_risk=0.4001, duration_s=2000)
    b = summary("Route B", 1, avg_risk=0.4004, duration_s=1000)  # equal at 3 decimals

    assert winner_of(a, b) == "Route B"


def test_ties_go_to_the_shorter_distance_then_the_lower_index():
    a = summary("Route A", 0, distance_mi=110)
    b = summary("Route B", 1, distance_mi=100)
    c = summary("Route C", 2, distance_mi=100)

    result = rank_routes([a, b, c])

    assert [entry.route_id for entry in result.ranking] == ["Route B", "Route C", "Route A"]
    assert [entry.rank for entry in result.ranking] == [1, 2, 3]


def test_ranking_entries_carry_the_rounded_sort_key():
    entry = rank_routes([summary("Route A", severe=1.26, high=2.0, avg_risk=0.12345, duration_s=60)]).ranking[0]

    assert entry.sort_key == (0.0, 1.3, 2.0, 0.123, 60)


def test_routes_without_forecast_data_rank_after_scored_routes():
    unscored = summary("Route A", 0, avg_risk=None, duration_s=100)
    scored = summary("Route B", 1, severe=40, avg_risk=2.5, duration_s=9000)

    result = rank_routes([unscored, scored])

    assert result.route_id == "Route B"
    assert result.reasons == ("Route B has forecast data and Route A has none.",)
    assert result.ranking[1].sort_key[3] is None


def test_single_route_is_recommended_with_a_note():
    result = rank_routes([summary("Route A")])

    assert result.route_id == "Route A"
    assert result.all_blocked is False
    assert result.reasons == ("Only one route was available, so no alternatives were compared.",)


def test_no_routes_is_an_error():
    with pytest.raises(ValueError):
        rank_routes([])


def test_blocked_route_loses_to_an_unblocked_one():
    result = rank_routes([summary("Route A", 0, no_travel=5), summary("Route B", 1, severe=30)])

    assert result.route_id == "Route B"
    assert result.all_blocked is False


def test_all_blocked_recommends_the_least_blocked_with_a_warning():
    result = rank_routes(
        [summary("Route A", 0, no_travel=40), summary("Route B", 1, no_travel=12.5)]
    )

    assert result.route_id == "Route B"
    assert result.all_blocked is True
    assert result.reasons[0].startswith("Every route has No Travel conditions.")
    assert "12.5 miles" in result.reasons[0]
    assert len(result.reasons) == 2


def test_all_blocked_says_fewest_when_the_winner_is_strictly_lower_than_every_other():
    result = rank_routes(
        [
            summary("Route A", 0, no_travel=40),
            summary("Route B", 1, no_travel=12.5),
            summary("Route C", 2, no_travel=25),
        ]
    )

    assert result.reasons[0] == (
        "Every route has No Travel conditions. Route B has the fewest (12.5 miles); "
        "do not treat it as a safe route."
    )


def test_all_blocked_with_equal_no_travel_miles_does_not_claim_the_fewest():
    # Equal No Travel miles everywhere, so the remaining measures decide: B has fewer Severe miles.
    result = rank_routes(
        [
            summary("Route A", 0, no_travel=40, severe=10),
            summary("Route B", 1, no_travel=40, severe=5),
            summary("Route C", 2, no_travel=40, severe=20),
        ]
    )

    assert result.route_id == "Route B"
    assert result.all_blocked is True
    assert result.reasons[0] == (
        "Every route has at least 40 miles of No Travel conditions. Route B ranks best on "
        "the remaining measures; do not treat it as a safe route."
    )
    assert "fewest" not in result.reasons[0]


def test_all_blocked_with_the_lowest_no_travel_miles_tied_does_not_claim_the_fewest():
    # B wins on Severe miles, but A has just as few No Travel miles, so B is not strictly lower.
    result = rank_routes(
        [
            summary("Route A", 0, no_travel=12.5, severe=5),
            summary("Route B", 1, no_travel=12.5, severe=0),
            summary("Route C", 2, no_travel=40),
        ]
    )

    assert result.route_id == "Route B"
    assert result.reasons[0].startswith("Every route has at least 12.5 miles of No Travel conditions.")
    assert "Route B ranks best on the remaining measures" in result.reasons[0]


def test_all_blocked_compares_no_travel_miles_to_a_tenth_of_a_mile():
    # 12.52 and 12.54 are both 12.5 in the ranking and on screen: equal, not "fewest".
    result = rank_routes(
        [summary("Route A", 0, no_travel=12.54, severe=1), summary("Route B", 1, no_travel=12.52, severe=0)]
    )

    assert result.route_id == "Route B"
    assert result.reasons[0].startswith("Every route has at least 12.5 miles of No Travel conditions.")


# Reason text, built from the first key where winner and runner-up differ.
def test_reason_when_the_winner_is_slower():
    a = summary("Route A", 0, severe=14, duration_s=3600)
    b = summary("Route B", 1, severe=0, duration_s=3600 + 38 * 60)

    assert rank_routes([a, b]).reasons == (
        "Route B has 0 Severe miles against 14 on Route A, and is 38 minutes slower.",
    )


def test_reason_when_the_winner_is_faster():
    a = summary("Route A", 0, severe=14, duration_s=3600 + 22 * 60)
    b = summary("Route B", 1, severe=0, duration_s=3600)

    assert rank_routes([a, b]).reasons == (
        "Route B has 0 Severe miles against 14 on Route A, and is 22 minutes faster.",
    )


def test_reason_when_the_time_is_identical():
    a = summary("Route A", 0, severe=14)
    b = summary("Route B", 1, severe=0)

    assert rank_routes([a, b]).reasons == ("Route B has 0 Severe miles against 14 on Route A.",)


def test_reason_when_the_difference_is_under_half_a_minute():
    a = summary("Route A", 0, severe=14, duration_s=3600)
    b = summary("Route B", 1, severe=0, duration_s=3620)

    assert rank_routes([a, b]).reasons == ("Route B has 0 Severe miles against 14 on Route A.",)


def test_reason_when_no_travel_miles_decide():
    a = summary("Route A", 0, no_travel=100)
    b = summary("Route B", 1, no_travel=0, duration_s=3600 + 5 * 60)

    assert rank_routes([a, b]).reasons[0] == (
        "Route B has 0 No Travel miles against 100 on Route A, and is 5 minutes slower."
    )


def test_reason_when_high_miles_decide():
    a = summary("Route A", 0, high=30.5, duration_s=7200)
    b = summary("Route B", 1, high=10, duration_s=7200 - 600)

    assert rank_routes([a, b]).reasons == (
        "Route B has 10 High miles against 30.5 on Route A, and is 10 minutes faster.",
    )


def test_reason_when_average_risk_decides():
    a = summary("Route A", 0, avg_risk=1.25, duration_s=3600)
    b = summary("Route B", 1, avg_risk=0.5, duration_s=3600 + 90 * 60)

    assert rank_routes([a, b]).reasons == (
        "Route B has lower average risk (0.500 against 1.250 on Route A), "
        "and is 90 minutes slower.",
    )


def test_reason_when_weather_is_equal_and_time_decides():
    a = summary("Route A", 0, duration_s=3600 + 12 * 60)
    b = summary("Route B", 1, duration_s=3600)

    assert rank_routes([a, b]).reasons == (
        "Weather is equal on both routes; Route B is 12 minutes faster.",
    )


def test_reason_when_weather_is_equal_across_three_routes():
    a = summary("Route A", 0, duration_s=3600)
    b = summary("Route B", 1, duration_s=3600 + 12 * 60)
    c = summary("Route C", 2, duration_s=3600 + 30 * 60)

    assert rank_routes([a, b, c]).reasons == (
        "Weather is equal across the routes; Route A is 12 minutes faster.",
    )


def test_reason_without_forecast_data_does_not_say_both_for_three_routes():
    def bare(label, index, duration_s):
        return summary(label, index, avg_risk=None, duration_s=duration_s)

    two = rank_routes([bare("Route A", 0, 3600), bare("Route B", 1, 3600 + 600)]).reasons[0]
    three = rank_routes([bare("Route A", 0, 3600), bare("Route B", 1, 3600 + 600), bare("Route C", 2, 7200)]).reasons[0]

    assert "both" in two
    assert three == "No route has forecast data; Route A is 10 minutes faster."


def test_reason_when_weather_and_time_are_equal_distance_decides():
    a = summary("Route A", 0, distance_mi=120)
    b = summary("Route B", 1, distance_mi=100)

    assert rank_routes([a, b]).reasons == (
        "Weather is equal and travel time is equal; Route B is shorter.",
    )


def test_reason_when_everything_is_equal():
    result = rank_routes([summary("Route A", 0), summary("Route B", 1)])

    assert result.reasons == ("The routes are equal on every measure; Route A is listed first.",)


def test_reason_compares_only_the_winner_and_the_runner_up():
    a = summary("Route A", 0, severe=30)
    b = summary("Route B", 1, severe=0)
    c = summary("Route C", 2, severe=10)

    assert rank_routes([a, b, c]).reasons[0].startswith("Route B has 0 Severe miles against 10 on Route C")
