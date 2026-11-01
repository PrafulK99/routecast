"""Open-Meteo 429 handling: classify the reason, retry only per-minute limits, keep the
reason in the logs and out of the API response."""

import logging
import re

import httpx
import pytest

from providers.errors import WeatherRateLimitedError
from providers.fakes import InMemoryCache
from providers.openmeteo import OpenMeteoWeatherProvider, rate_limit_kind, rate_limit_reason
from providers.request_context import request_id_var

from .test_openmeteo_provider import NOW, TONIGHT, Stub, make_provider

POINT = [(32.8, -96.8)]
MINUTELY = "Minutely API request limit exceeded. Please try again in one minute."
HOURLY = "Hourly API request limit exceeded. Please try again in the next hour."
DAILY = "Daily API request limit exceeded. Please try again tomorrow."


def limited(reason=MINUTELY):
    return httpx.Response(429, json={"error": True, "reason": reason})


def answers(*responses):
    """A Stub responder that plays the given responses in order; None means a normal reply."""
    queue = iter(responses)
    return lambda request: next(queue, None)


@pytest.fixture
def request_id():
    token = request_id_var.set("req-123")
    yield "req-123"
    request_id_var.reset(token)


# --- classification -------------------------------------------------------------


@pytest.mark.parametrize(
    "reason, kind",
    [
        (MINUTELY, "minutely"),
        (HOURLY, "hourly"),
        (DAILY, "daily"),
        ("MINUTELY API REQUEST LIMIT EXCEEDED", "minutely"),
        ("Too many concurrent requests", "unknown"),
        ("", "unknown"),
    ],
)
def test_the_reason_text_classifies_the_limit(reason, kind):
    assert rate_limit_kind(reason) == kind


@pytest.mark.parametrize(
    "response, expected",
    [
        (httpx.Response(429, json={"reason": "  two\nlines\t here "}), "two lines here"),
        (httpx.Response(429, json={"reason": "x" * 500}), "x" * 200),
        (httpx.Response(429, json={"reason": "see https://api.open-meteo.com/v1?apikey=SECRET now"}), "see [url] now"),
        (httpx.Response(429, json={"error": True}), ""),
        (httpx.Response(429, json={"reason": ["not", "a", "string"]}), ""),
        (httpx.Response(429, json=["unexpected"]), ""),
        (httpx.Response(429, content=b"<html>slow down</html>"), ""),
    ],
)
def test_the_reason_is_cleaned_for_the_logs(response, expected):
    assert rate_limit_reason(response) == expected


# --- minutely limits are retried ------------------------------------------------


def test_a_minutely_limit_recovers_on_the_second_try():
    stub = Stub(answers(limited(MINUTELY), None))
    sleeps = []

    result = make_provider(stub, sleeps=sleeps).get_series(POINT, TONIGHT)

    assert len(stub.requests) == 2
    assert sleeps == [2.0]
    assert len(result.series) == 1 and result.failed_cells == frozenset()


def test_a_minutely_limit_can_recover_on_the_third_try():
    stub = Stub(answers(limited(), limited(), None))
    sleeps = []

    result = make_provider(stub, sleeps=sleeps).get_series(POINT, TONIGHT)

    assert len(stub.requests) == 3
    assert sleeps == [2.0, 5.0]
    assert len(result.series) == 1


def test_a_minutely_limit_that_persists_fails_after_two_retries():
    stub = Stub(lambda request: limited())
    sleeps = []

    with pytest.raises(WeatherRateLimitedError) as raised:
        make_provider(stub, sleeps=sleeps).get_series(POINT, TONIGHT)

    assert len(stub.requests) == 3  # the request and two retries
    assert sleeps == [2.0, 5.0]
    assert str(raised.value) == "The weather service is rate limited; try again in a minute."


def test_the_total_extra_wait_stays_under_ten_seconds_even_with_maximum_jitter():
    sleeps = []
    provider = make_provider(Stub(lambda request: limited()), sleeps=sleeps)
    provider._jitter = lambda limit: limit

    with pytest.raises(WeatherRateLimitedError):
        provider.get_series(POINT, TONIGHT)

    assert sleeps == [2.5, 5.5]
    assert sum(sleeps) < 10


def test_the_default_jitter_is_small_and_random():
    sleeps = []
    provider = OpenMeteoWeatherProvider(
        httpx.Client(transport=httpx.MockTransport(Stub(lambda request: limited()))),
        InMemoryCache(),
        clock=lambda: NOW,
        sleep=sleeps.append,
    )

    with pytest.raises(WeatherRateLimitedError):
        provider.get_series(POINT, TONIGHT)

    assert 2.0 <= sleeps[0] <= 2.5 and 5.0 <= sleeps[1] <= 5.5


def test_a_server_error_during_the_waits_still_gets_its_own_single_retry():
    stub = Stub(answers(limited(), httpx.Response(500), None))
    sleeps = []

    result = make_provider(stub, sleeps=sleeps).get_series(POINT, TONIGHT)

    assert len(stub.requests) == 3
    assert sleeps == [2.0, 0.5]
    assert len(result.series) == 1


# --- everything else is not retried ---------------------------------------------


@pytest.mark.parametrize("reason", [HOURLY, DAILY])
def test_hourly_and_daily_limits_raise_immediately(reason):
    stub = Stub(lambda request: limited(reason))
    sleeps = []

    with pytest.raises(WeatherRateLimitedError) as raised:
        make_provider(stub, sleeps=sleeps).get_series(POINT, TONIGHT)

    assert len(stub.requests) == 1
    assert sleeps == []
    assert str(raised.value) == "The weather service is rate limited; try again later."


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, json={"error": True}),
        httpx.Response(429, json={"reason": "Too many concurrent requests"}),
        httpx.Response(429, content=b"<html>slow down</html>"),
    ],
    ids=["no reason", "unknown reason", "not json"],
)
def test_an_unclassified_limit_raises_immediately_with_the_later_message(response):
    stub = Stub(lambda request: response)

    with pytest.raises(WeatherRateLimitedError) as raised:
        make_provider(stub).get_series(POINT, TONIGHT)

    assert len(stub.requests) == 1
    assert "try again later" in str(raised.value)


def test_the_reason_never_appears_in_the_error():
    stub = Stub(lambda request: limited("Hourly limit exceeded for key abc-SECRET-123"))

    with pytest.raises(WeatherRateLimitedError) as raised:
        make_provider(stub).get_series(POINT, TONIGHT)

    assert "SECRET" not in str(raised.value) and "Hourly limit" not in str(raised.value)


# --- logging --------------------------------------------------------------------


def test_the_reason_is_logged_at_warning_with_the_request_id(request_id, caplog):
    stub = Stub(lambda request: limited(HOURLY))

    with caplog.at_level(logging.INFO), pytest.raises(WeatherRateLimitedError):
        make_provider(stub).get_series(POINT, TONIGHT)

    (record,) = [r for r in caplog.records if r.name == "routecast.weather"]
    assert record.levelno == logging.WARNING
    assert f"request_id={request_id}" in record.getMessage()
    assert "kind=hourly" in record.getMessage()
    assert HOURLY in record.getMessage()


def test_a_long_reason_is_truncated_to_200_characters_in_the_log(request_id, caplog):
    stub = Stub(lambda request: limited("Hourly " + "x" * 500))

    with caplog.at_level(logging.INFO), pytest.raises(WeatherRateLimitedError):
        make_provider(stub).get_series(POINT, TONIGHT)

    message = next(r.getMessage() for r in caplog.records if r.name == "routecast.weather")
    logged_reason = re.search(r"reason='(.*)'$", message).group(1)
    assert len(logged_reason) == 200


def test_every_retry_is_logged_with_its_own_reason(request_id, caplog):
    stub = Stub(lambda request: limited())

    with caplog.at_level(logging.INFO), pytest.raises(WeatherRateLimitedError):
        make_provider(stub).get_series(POINT, TONIGHT)

    assert len([r for r in caplog.records if r.name == "routecast.weather"]) == 3


def test_no_secret_or_url_appears_in_the_logs(request_id, caplog):
    secret_reason = "Hourly limit hit. Docs: https://api.open-meteo.com/v1/forecast?apikey=SECRET123&latitude=32.8"
    stub = Stub(lambda request: limited(secret_reason))

    with caplog.at_level(logging.DEBUG), pytest.raises(WeatherRateLimitedError):
        make_provider(stub).get_series(POINT, TONIGHT)

    text = " ".join(r.getMessage() for r in caplog.records)
    assert "Hourly limit hit" in text  # the useful part is kept
    assert "SECRET123" not in text and "://" not in text and "open-meteo.com" not in text
    assert "32.8" not in text  # no request parameters either
