import math

import pytest

from domain.constants import Level
from domain.models import WeatherSample
from domain.risk import (
    apply_load_rules,
    assess_risk,
    classify_rain,
    classify_snow,
    classify_wind,
)

L, M, H, S, N = Level.LOW, Level.MODERATE, Level.HIGH, Level.SEVERE, Level.NO_TRAVEL

# (value, expected level): every bound and the value just below it.
WIND_CASES = [
    (0, L), (24.9, L), (24.99, L), (25, M), (34.9, M), (34.99, M), (35, H),
    (44.9, H), (44.99, H), (45, S), (54.9, S), (54.99, S), (55, N), (80, N),
]  # fmt: skip
RAIN_CASES = [
    (0, L), (0.09, L), (0.0999, L), (0.10, M), (0.24, M), (0.2499, M), (0.25, H),
    (0.49, H), (0.4999, H), (0.50, S), (0.99, S), (1.00, S), (1.0001, N), (1.01, N),
]  # fmt: skip
SNOW_CASES = [
    (0, L), (0.49, L), (0.4999, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H),
    (2.0, S), (2.99, S), (3.0, S), (3.0001, N), (3.01, N),
]  # fmt: skip


@pytest.mark.parametrize("value, expected", WIND_CASES)
def test_wind_thresholds(value, expected):
    assert classify_wind(value) == expected


@pytest.mark.parametrize("value, expected", RAIN_CASES)
def test_rain_thresholds(value, expected):
    assert classify_rain(value) == expected


@pytest.mark.parametrize("value, expected", SNOW_CASES)
def test_snow_thresholds(value, expected):
    assert classify_snow(value) == expected


# (wind, load, expected load-rule level)
LOAD_RULE_CASES = [
    (55, 0, N), (60, 0, N),
    (54.9, 30_000, L), (54.9, 30_001, N), (45, 30_000, L), (45, 30_001, N),
    (50, 29_999, L), (50, 200_000, N),
    (44.9, 40_000, L), (44.9, 40_001, S), (35, 40_000, L), (35, 40_001, S),
    (40, 39_999, L), (40, 45_000, S),
    (34.9, 200_000, L), (10, 200_000, L),
]  # fmt: skip


@pytest.mark.parametrize("wind, load, expected", LOAD_RULE_CASES)
def test_load_rules(wind, load, expected):
    assert apply_load_rules(wind, load) == expected


# (wind, rain, snow, load, expected level, expected factor): the design's worked examples.
WORKED_EXAMPLES = [
    (38, 0.05, 0, 45_000, S, "wind"),
    (38, 0.05, 0, 40_000, H, "wind"),
    (47, 0, 0, 30_001, N, "wind"),
    (47, 0, 0, 30_000, S, "wind"),
    (55, 0, 0, 0, N, "wind"),
    (20, 0.30, 0, 50_000, H, "rain"),
    (10, 1.00, 0, 10_000, S, "rain"),
    (10, 1.01, 0, 10_000, N, "rain"),
    (34.9, 0, 0, 10_000, M, "wind"),
]


@pytest.mark.parametrize("wind, rain, snow, load, level, factor", WORKED_EXAMPLES)
def test_worked_examples(wind, rain, snow, load, level, factor):
    result = assess_risk(WeatherSample(wind, rain, snow), load)

    assert result.level == level
    assert result.factor == factor
    assert result.status == "ok"


def test_load_rule_applied_flag():
    raised = assess_risk(WeatherSample(38, 0.05, 0), 45_000)
    not_raised = assess_risk(WeatherSample(38, 0.05, 0), 40_000)
    rain_dominates = assess_risk(WeatherSample(38, 0.60, 0), 45_000)

    assert raised.load_rule_applied is True
    assert raised.wind_level == S
    assert not_raised.load_rule_applied is False
    assert rain_dominates.level == S
    assert rain_dominates.load_rule_applied is False


def test_rain_and_snow_ignore_load():
    light = assess_risk(WeatherSample(0, 0.30, 2.5), 0)
    heavy = assess_risk(WeatherSample(0, 0.30, 2.5), 200_000)

    assert light == heavy


def test_individual_levels_are_reported():
    result = assess_risk(WeatherSample(30, 0.30, 2.5), 0)

    assert (result.wind_level, result.rain_level, result.snow_level) == (M, H, S)
    assert result.level == S
    assert result.factor == "snow"


@pytest.mark.parametrize(
    "sample, factor",
    [
        (WeatherSample(50, 0.60, 2.5), "wind"),  # all Severe: wind wins
        (WeatherSample(10, 0.60, 2.5), "rain"),  # rain and snow Severe: rain wins
        (WeatherSample(10, 0, 2.5), "snow"),
    ],
)
def test_tie_goes_to_wind_then_rain_then_snow(sample, factor):
    assert assess_risk(sample, 0).factor == factor


# Missing data: never treated as zero, never Low.
def test_partial_sample_is_classified_with_present_values():
    result = assess_risk(WeatherSample(wind_mph=47), 0)

    assert result.status == "partial"
    assert result.level == S
    assert result.rain_level is None and result.snow_level is None


def test_partial_sample_with_load_rule():
    assert assess_risk(WeatherSample(wind_mph=47), 30_001).level == N


@pytest.mark.parametrize("sample", [None, WeatherSample()])
def test_all_missing_is_unavailable_not_low(sample):
    result = assess_risk(sample, 50_000)

    assert result.status == "unavailable"
    assert result.level is None
    assert result.factor is None
    assert result.load_rule_applied is False


def test_missing_wind_does_not_trigger_load_rules():
    result = assess_risk(WeatherSample(rain_in_hr=0.05), 200_000)

    assert result.level == L
    assert result.status == "partial"


@pytest.mark.parametrize("bad", [-0.1, math.nan, math.inf, -math.inf])
def test_invalid_weather_raises(bad):
    with pytest.raises(ValueError):
        assess_risk(WeatherSample(wind_mph=bad), 0)
    with pytest.raises(ValueError):
        assess_risk(WeatherSample(rain_in_hr=bad), 0)
    with pytest.raises(ValueError):
        assess_risk(WeatherSample(snow_in_hr=bad), 0)


@pytest.mark.parametrize("bad", [-1, math.nan, math.inf])
def test_invalid_load_raises(bad):
    with pytest.raises(ValueError):
        assess_risk(WeatherSample(10, 0, 0), bad)
