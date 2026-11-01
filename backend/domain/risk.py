"""The risk engine: weather values and load weight in, a level and its reasons out."""

import math

from .constants import (
    LOAD_RULES,
    RAIN_LOWER_BOUNDS_IN_HR,
    RAIN_NO_TRAVEL_OVER_IN_HR,
    SNOW_LOWER_BOUNDS_IN_HR,
    SNOW_NO_TRAVEL_OVER_IN_HR,
    WIND_LOWER_BOUNDS_MPH,
    Level,
)
from .models import RiskResult, WeatherSample

# On a tie the earlier factor wins (DESIGN: wind, then rain, then snow).
_FACTORS = ("wind", "rain", "snow")


def _validate(name, value):
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be finite and not negative, got {value!r}")


def _level_from_bounds(value, bounds):
    level = Level.LOW
    for lower_bound, bound_level in bounds:
        if value >= lower_bound:
            level = bound_level
    return level


def classify_wind(wind_mph: float) -> Level:
    _validate("wind_mph", wind_mph)
    return _level_from_bounds(wind_mph, WIND_LOWER_BOUNDS_MPH)


def classify_rain(rain_in_hr: float) -> Level:
    _validate("rain_in_hr", rain_in_hr)
    if rain_in_hr > RAIN_NO_TRAVEL_OVER_IN_HR:
        return Level.NO_TRAVEL
    return _level_from_bounds(rain_in_hr, RAIN_LOWER_BOUNDS_IN_HR)


def classify_snow(snow_in_hr: float) -> Level:
    _validate("snow_in_hr", snow_in_hr)
    if snow_in_hr > SNOW_NO_TRAVEL_OVER_IN_HR:
        return Level.NO_TRAVEL
    return _level_from_bounds(snow_in_hr, SNOW_LOWER_BOUNDS_IN_HR)


def apply_load_rules(wind_mph: float, load_weight_lb: float) -> Level:
    """Level demanded by the load rules alone (Low when none applies).

    A rule needs the load strictly greater than its weight.
    """
    _validate("wind_mph", wind_mph)
    _validate("load_weight_lb", load_weight_lb)
    level = Level.LOW
    for rule in LOAD_RULES:
        in_wind_range = wind_mph >= rule.wind_min_mph and (
            rule.wind_max_mph is None or wind_mph < rule.wind_max_mph
        )
        heavy_enough = rule.load_over_lb is None or load_weight_lb > rule.load_over_lb
        if in_wind_range and heavy_enough:
            level = max(level, rule.result)
    return level


def _checkpoint_level(wind_level, rain_level, snow_level):
    """Highest present level and the factor that set it, or (None, None)."""
    levels = {"wind": wind_level, "rain": rain_level, "snow": snow_level}
    present = {factor: level for factor, level in levels.items() if level is not None}
    if not present:
        return None, None
    top = max(present.values())
    return top, next(factor for factor in _FACTORS if present.get(factor) == top)


def assess_risk(sample: WeatherSample | None, load_weight_lb: float) -> RiskResult:
    """Classify one checkpoint.

    None, or a sample with every value missing, gives status unavailable and no
    level, never Low. Some values missing gives status partial.
    """
    _validate("load_weight_lb", load_weight_lb)
    sample = sample or WeatherSample()
    rain_level = None if sample.rain_in_hr is None else classify_rain(sample.rain_in_hr)
    snow_level = None if sample.snow_in_hr is None else classify_snow(sample.snow_in_hr)

    table_wind_level = None
    wind_level = None
    if sample.wind_mph is not None:
        table_wind_level = classify_wind(sample.wind_mph)
        wind_level = max(table_wind_level, apply_load_rules(sample.wind_mph, load_weight_lb))

    level, factor = _checkpoint_level(wind_level, rain_level, snow_level)
    level_without_rules, _ = _checkpoint_level(table_wind_level, rain_level, snow_level)

    present = sum(v is not None for v in (sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr))
    status = "unavailable" if present == 0 else "ok" if present == 3 else "partial"
    return RiskResult(
        level=level,
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        factor=factor,
        load_rule_applied=level is not None and level > level_without_rules,
        status=status,
    )
