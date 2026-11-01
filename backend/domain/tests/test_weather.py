from datetime import datetime, timedelta, timezone

import pytest

from domain.constants import Level
from domain.models import WeatherSample
from domain.risk import assess_risk
from domain.weather import weather_at

START = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
SAMPLE = WeatherSample(wind_mph=47, rain_in_hr=0.0, snow_in_hr=0.0)

# Hours 10:00, 11:00, 13:00 and 14:00 exist; 12:00 is a hole.
SERIES = {START + timedelta(hours=h): SAMPLE for h in (0, 1, 3, 4)}


def test_hour_in_series_returns_its_sample():
    assert weather_at(SERIES, START + timedelta(hours=3)) is SAMPLE


@pytest.mark.parametrize(
    "offset_hours",
    [-1, 5, 2],
    ids=["before the series start", "after the series end", "hole in the middle"],
)
def test_missing_hour_returns_none(offset_hours):
    assert weather_at(SERIES, START + timedelta(hours=offset_hours)) is None


def test_lookup_matches_the_same_instant_in_another_zone():
    local = (START + timedelta(hours=1)).astimezone(timezone(timedelta(hours=-6)))

    assert weather_at(SERIES, local) is SAMPLE


def test_naive_hour_is_rejected():
    with pytest.raises(ValueError):
        weather_at(SERIES, datetime(2026, 11, 2, 10, 0))


@pytest.mark.parametrize("offset_hours", [-1, 5, 2])
def test_missing_hour_makes_an_unavailable_checkpoint_never_low(offset_hours):
    sample = weather_at(SERIES, START + timedelta(hours=offset_hours))

    risk = assess_risk(sample, 50_000)

    assert risk.status == "unavailable"
    assert risk.level is None
    assert risk.level != Level.LOW
