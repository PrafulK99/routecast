from datetime import datetime, timedelta, timezone

import pytest

from domain.models import WeatherSample
from providers.openmeteo import parse_forecast

from .helpers import load_fixture, openmeteo_body

UTC = timezone.utc
MIDNIGHT = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)


def hour(n):
    return MIDNIGHT + timedelta(hours=n)


def test_parses_one_series_per_location_in_request_order():
    series = parse_forecast(openmeteo_body())

    assert len(series) == 3
    assert all(len(s) == 48 for s in series)


def test_timestamps_are_parsed_as_timezone_aware_utc():
    series = parse_forecast(openmeteo_body())[0]

    assert min(series) == MIDNIGHT
    assert all(key.utcoffset() == timedelta(0) for key in series)
    assert hour(5) in series  # a lookup by an aware UTC datetime works


def test_series_includes_hours_before_now():
    recorded_at = datetime.fromisoformat(load_fixture("openmeteo_three_cells.json")["recorded_at"])

    series = parse_forecast(openmeteo_body())[0]

    assert min(series) < recorded_at - timedelta(hours=12)


def test_values_come_from_the_recorded_response():
    body = openmeteo_body()
    hourly = body[0]["hourly"]

    sample = parse_forecast(body)[0][hour(3)]

    assert sample == WeatherSample(
        wind_mph=hourly["wind_speed_10m"][3],
        rain_in_hr=hourly["rain"][3] + hourly["showers"][3],
        snow_in_hr=hourly["snowfall"][3],
    )
    assert sample.wind_mph == 3.1


def test_rain_is_rain_plus_showers():
    body = openmeteo_body()
    body[0]["hourly"]["rain"][5] = 0.10
    body[0]["hourly"]["showers"][5] = 0.05

    assert parse_forecast(body)[0][hour(5)].rain_in_hr == pytest.approx(0.15)


def test_snowfall_is_read_as_inches_without_conversion():
    body = openmeteo_body()
    body[0]["hourly"]["snowfall"][5] = 1.5

    assert parse_forecast(body)[0][hour(5)].snow_in_hr == 1.5


@pytest.mark.parametrize(
    "variable, field",
    [("wind_speed_10m", "wind_mph"), ("snowfall", "snow_in_hr")],
)
def test_a_null_value_becomes_none_not_zero(variable, field):
    body = openmeteo_body()
    body[0]["hourly"][variable][7] = None

    sample = parse_forecast(body)[0][hour(7)]

    assert getattr(sample, field) is None
    # The other fields at that hour are untouched.
    assert sum(v is None for v in (sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr)) == 1


@pytest.mark.parametrize("variable", ["rain", "showers"])
def test_rain_is_unknown_when_either_part_is_null(variable):
    body = openmeteo_body()
    body[0]["hourly"]["rain"][7] = 0.10
    body[0]["hourly"]["showers"][7] = 0.05
    body[0]["hourly"][variable][7] = None

    assert parse_forecast(body)[0][hour(7)].rain_in_hr is None


def test_an_hour_with_every_value_null_is_an_empty_sample():
    body = openmeteo_body()
    for variable in ("wind_speed_10m", "rain", "showers", "snowfall"):
        body[0]["hourly"][variable][9] = None

    assert parse_forecast(body)[0][hour(9)] == WeatherSample()


def test_a_hole_in_the_hourly_series_leaves_that_hour_absent():
    body = openmeteo_body()
    hourly = body[0]["hourly"]
    hourly["wind_speed_10m"][6] = 77.0  # the hour after the hole
    for values in hourly.values():
        del values[5]  # 05:00 is missing from every array

    series = parse_forecast(body)[0]

    assert hour(5) not in series
    assert len(series) == 47
    # Values stay with their own timestamp; nothing shifts into the hole.
    assert series[hour(6)].wind_mph == 77.0
    assert series[hour(4)].wind_mph == openmeteo_body()[0]["hourly"]["wind_speed_10m"][4]


def test_the_unit_label_is_not_relied_on():
    body = openmeteo_body()
    body[0]["hourly_units"]["wind_speed_10m"] = "km/h"

    assert parse_forecast(body) == parse_forecast(openmeteo_body())


def test_a_single_location_arrives_as_an_object():
    body = openmeteo_body()

    assert parse_forecast(body[0]) == parse_forecast(body)[:1]


def test_a_variable_missing_from_the_response_is_none():
    body = openmeteo_body()
    del body[0]["hourly"]["snowfall"]

    assert parse_forecast(body)[0][hour(0)].snow_in_hr is None


def test_a_time_with_an_offset_is_converted_to_utc():
    body = openmeteo_body()
    body[0]["hourly"]["time"][0] = "2026-11-01T01:00+01:00"

    assert hour(0) in parse_forecast(body)[0]


def test_a_malformed_location_raises():
    with pytest.raises(KeyError):
        parse_forecast([{"latitude": 1.0}])
