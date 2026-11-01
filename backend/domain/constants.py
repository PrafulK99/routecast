"""Every threshold, load rule and tunable number of the domain engine.

Source of truth: docs/DESIGN.md (Risk engine, Route scoring, pipeline).
Units: miles, mph, inches per hour, pounds. Time is UTC.
"""

from enum import IntEnum
from typing import NamedTuple


class Level(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4


LEVEL_NAMES = {
    Level.LOW: "Low",
    Level.MODERATE: "Moderate",
    Level.HIGH: "High",
    Level.SEVERE: "Severe",
    Level.NO_TRAVEL: "No Travel",
}

# Each level starts at its lower bound (inclusive) and runs up to, not including,
# the next bound (decision 4). Bounds are listed from lowest to highest level.
WIND_LOWER_BOUNDS_MPH = (
    (25.0, Level.MODERATE),
    (35.0, Level.HIGH),
    (45.0, Level.SEVERE),
    (55.0, Level.NO_TRAVEL),
)
RAIN_LOWER_BOUNDS_IN_HR = (
    (0.10, Level.MODERATE),
    (0.25, Level.HIGH),
    (0.50, Level.SEVERE),
)
SNOW_LOWER_BOUNDS_IN_HR = (
    (0.5, Level.MODERATE),
    (1.0, Level.HIGH),
    (2.0, Level.SEVERE),
)
# Rain and snow keep the spec's strict "over" for No Travel: exactly the cap is Severe.
RAIN_NO_TRAVEL_OVER_IN_HR = 1.00
SNOW_NO_TRAVEL_OVER_IN_HR = 3.0


class LoadRule(NamedTuple):
    """Raises the wind level to `result` when wind_min <= wind < wind_max and the
    load is strictly greater than `load_over_lb` (None means any load)."""

    wind_min_mph: float
    wind_max_mph: float | None
    load_over_lb: int | None
    result: Level


LOAD_RULES = (
    LoadRule(55.0, None, None, Level.NO_TRAVEL),
    LoadRule(45.0, 55.0, 30_000, Level.NO_TRAVEL),
    LoadRule(35.0, 45.0, 40_000, Level.SEVERE),
)

# Checkpoints and ETA
ALLOWED_INTERVALS_MILES = (10, 25, 50)
DEFAULT_INTERVAL_MILES = 25
MAX_CHECKPOINTS_PER_ROUTE = 150
DEFAULT_TRUCK_FACTOR = 1.10
MILE_EPSILON = 1e-6

# Corridor points for the heatmap
CORRIDOR_SPACING_MILES = 15
CORRIDOR_POINT_CAP = 120  # each grid cell is one Open-Meteo call against a daily quota
CORRIDOR_SPACING_GROWTH = 1.5
GRID_DECIMALS = 1

# Geometry sent to the browser
DISPLAY_TOLERANCE_MILES = 0.031  # about 50 m
DISPLAY_MAX_POINTS = 2000

# Ranking
MILES_ROUNDING_DECIMALS = 1
RISK_ROUNDING_DECIMALS = 3
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
