"""Strict lexicographic ranking and the recommendation reason
(docs/DESIGN.md, Route scoring and recommendation)."""

from typing import Sequence

from .constants import (
    MILES_ROUNDING_DECIMALS,
    RISK_ROUNDING_DECIMALS,
    SECONDS_PER_MINUTE,
    Level,
)
from .models import RankingEntry, Recommendation, RouteSummary

# The weather keys that can decide a ranking, in order, with their display names.
_MILE_KEYS = ((Level.NO_TRAVEL, "No Travel"), (Level.SEVERE, "Severe"), (Level.HIGH, "High"))


def _sort_key(summary: RouteSummary) -> tuple[float, float, float, float | None, float]:
    """(No Travel mi, Severe mi, High mi, average risk, duration) after rounding,
    so floating-point noise cannot decide a ranking."""
    miles = [
        round(summary.miles_by_level[level], MILES_ROUNDING_DECIMALS) for level, _ in _MILE_KEYS
    ]
    avg_risk = (
        None if summary.avg_risk is None else round(summary.avg_risk, RISK_ROUNDING_DECIMALS)
    )
    return (*miles, avg_risk, summary.duration_s)


def _order(summary: RouteSummary):
    """Routes with no scored miles come last, then the five keys, then the
    shorter distance, then the lower route index."""
    *miles, avg_risk, duration_s = _sort_key(summary)
    return (
        summary.avg_risk is None,
        *miles,
        avg_risk or 0.0,
        duration_s,
        summary.distance_mi,
        summary.route_index,
    )


def _number(value: float) -> str:
    rounded = round(value, MILES_ROUNDING_DECIMALS)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _time_clause(winner: RouteSummary, runner_up: RouteSummary) -> str:
    minutes = round((winner.duration_s - runner_up.duration_s) / SECONDS_PER_MINUTE)
    if minutes == 0:
        return ""
    return f"{abs(minutes)} minutes {'slower' if minutes > 0 else 'faster'}"


def _reason(winner: RouteSummary, runner_up: RouteSummary) -> str:
    """Built from the first key where the winner differs from the runner-up."""
    time_clause = _time_clause(winner, runner_up)
    win_key, other_key = _sort_key(winner), _sort_key(runner_up)

    if (winner.avg_risk is None) != (runner_up.avg_risk is None):
        return f"{winner.label} has forecast data and {runner_up.label} has none."
    if winner.avg_risk is not None:
        for position, (_, name) in enumerate(_MILE_KEYS):
            if win_key[position] != other_key[position]:
                text = (
                    f"{winner.label} has {_number(win_key[position])} {name} miles "
                    f"against {_number(other_key[position])} on {runner_up.label}"
                )
                return text + (f", and is {time_clause}." if time_clause else ".")
        if win_key[3] != other_key[3]:
            text = (
                f"{winner.label} has lower average risk "
                f"({win_key[3]:.{RISK_ROUNDING_DECIMALS}f} against "
                f"{other_key[3]:.{RISK_ROUNDING_DECIMALS}f} on {runner_up.label})"
            )
            return text + (f", and is {time_clause}." if time_clause else ".")

    weather = "Weather is equal" if winner.avg_risk is not None else "Neither route has forecast data"
    if time_clause:
        return f"{weather} on both routes; {winner.label} is {time_clause}."
    if winner.distance_mi != runner_up.distance_mi:
        return f"{weather} and travel time is equal; {winner.label} is shorter."
    return f"The routes are equal on every measure; {winner.label} is listed first."


def rank_routes(summaries: Sequence[RouteSummary]) -> Recommendation:
    """Rank every route and name the first as recommended, with reasons."""
    if not summaries:
        raise ValueError("need at least one route to rank")

    ordered = sorted(summaries, key=_order)
    ranking = tuple(
        RankingEntry(rank=rank, route_id=summary.route_id, sort_key=_sort_key(summary))
        for rank, summary in enumerate(ordered, start=1)
    )
    winner = ordered[0]
    all_blocked = all(summary.blocked for summary in ordered)

    reasons = []
    if all_blocked:
        # Compared as the ranking compares them, to a tenth of a mile.
        no_travel = {s.route_id: _sort_key(s)[0] for s in ordered}
        winner_miles = no_travel[winner.route_id]
        fewest = all(winner_miles < miles for route_id, miles in no_travel.items() if route_id != winner.route_id)
        if fewest:
            reasons.append(
                f"Every route has No Travel conditions. {winner.label} has the fewest "
                f"({_number(winner_miles)} miles); do not treat it as a safe route."
            )
        else:
            reasons.append(
                f"Every route has at least {_number(winner_miles)} miles of No Travel conditions. "
                f"{winner.label} ranks best on the remaining measures; do not treat it as a safe route."
            )
    if len(ordered) == 1:
        reasons.append("Only one route was available, so no alternatives were compared.")
    else:
        reasons.append(_reason(winner, ordered[1]))

    return Recommendation(
        route_id=winner.route_id,
        reasons=tuple(reasons),
        all_blocked=all_blocked,
        ranking=ranking,
    )
