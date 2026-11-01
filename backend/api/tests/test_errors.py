"""One test per error code, the shared error shape, the throttle and its proxy handling."""

import logging

import pytest

from providers.errors import (
    NoRouteError,
    RoutingUnavailableError,
    WeatherRateLimitedError,
    WeatherUnavailableError,
)
from providers.fakes import FakeRoutingProvider

from .helpers import (
    REQUEST_ID,
    ScenarioWeather,
    analyze_payload,
    calm,
    heatmap_payload,
    routes,
    LINE_A,
)

ANALYZE, HEATMAP = "/api/analyze", "/api/heatmap"


def post(client, url=ANALYZE, payload=None, **extra):
    return client.post(url, analyze_payload() if payload is None else payload, format="json", **extra)


def assert_error(response, status, code):
    assert response.status_code == status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "fields", "request_id"}
    assert error["code"] == code
    assert error["message"] and isinstance(error["fields"], dict)
    # The request id is in the body and the header, and they agree.
    assert error["request_id"] == REQUEST_ID == response["X-Request-ID"]
    return error


# --- one test per error code ----------------------------------------------------


def test_validation_error_400(client, providers):
    providers()

    error = assert_error(post(client, payload={}), 400, "validation_error")

    assert set(error["fields"]) == {"origin", "destination", "departure_time", "load_weight_lb"}
    assert all(isinstance(messages, list) and messages for messages in error["fields"].values())


def test_no_route_422(client, providers):
    providers(FakeRoutingProvider(error=NoRouteError("No drivable route was found between these points.")))

    error = assert_error(post(client), 422, "no_route")

    assert error["message"] == "No drivable route was found between these points."


def test_route_too_long_422(client, providers, settings):
    providers(routes((LINE_A, 60.0)))
    settings.MAX_CHECKPOINTS_PER_ROUTE = 5  # 240 miles needs 6 checkpoints even at 50 miles

    error = assert_error(post(client, payload=analyze_payload(checkpoint_interval_miles=50)), 422, "route_too_long")

    assert "50-mile spacing" in error["message"]


def test_routing_unavailable_502(client, providers):
    providers(FakeRoutingProvider(error=RoutingUnavailableError("Mapbox did not respond after one retry.")))

    assert_error(post(client), 502, "routing_unavailable")


def test_weather_unavailable_502(client, providers):
    providers(weather=ScenarioWeather(calm, error=WeatherUnavailableError("down")))

    assert_error(post(client), 502, "weather_unavailable")


def test_weather_rate_limited_503(client, providers):
    providers(weather=ScenarioWeather(calm, error=WeatherRateLimitedError("slow down")))

    assert_error(post(client), 503, "weather_rate_limited")


def test_internal_error_500_hides_the_details(client, providers, caplog):
    providers(FakeRoutingProvider(error=RuntimeError("secret detail at /srv/app/secret.py")))
    caplog.set_level(logging.ERROR)

    response = post(client)

    assert_error(response, 500, "internal_error")
    assert "secret" not in response.content.decode() and "Traceback" not in response.content.decode()
    # The stack trace goes to the log, tagged with the request id.
    record = next(r for r in caplog.records if r.name == "routecast.api")
    assert REQUEST_ID in record.getMessage() and record.exc_info is not None


def test_rate_limited_429_on_the_31st_request(client, providers):
    providers()

    for _ in range(30):
        assert post(client, payload={}).status_code == 400  # counted even when invalid

    error = assert_error(post(client, payload={}), 429, "rate_limited")
    assert "Try again in" in error["message"]
    assert int(client.post(ANALYZE, {}, format="json")["Retry-After"]) > 0


def test_the_budget_is_shared_by_both_endpoints(client, providers):
    providers()
    for _ in range(15):
        post(client, ANALYZE, {})
        post(client, HEATMAP, {})

    assert_error(post(client, HEATMAP, {}), 429, "rate_limited")
    assert_error(post(client, ANALYZE, {}), 429, "rate_limited")


def test_health_is_never_throttled(client):
    assert all(client.get("/api/health").status_code == 200 for _ in range(40))


# --- other shapes ---------------------------------------------------------------


def test_malformed_json_is_a_validation_error(client):
    response = client.post(ANALYZE, "{not json", content_type="application/json")

    error = assert_error(response, 400, "validation_error")

    assert error["message"] == "The request body is not valid JSON."


def test_wrong_method_keeps_its_status_in_the_same_shape(client):
    response = client.get(ANALYZE)

    assert_error(response, 405, "method_not_allowed")
    assert "POST" in response["Allow"]


def test_success_responses_carry_the_request_id_header(client, providers):
    providers()

    assert post(client)["X-Request-ID"] == REQUEST_ID
    assert client.get("/api/health")["X-Request-ID"] == REQUEST_ID


# --- throttle behind a proxy ----------------------------------------------------


def exhaust(client, forwarded_for):
    for _ in range(30):
        post(client, payload={}, HTTP_X_FORWARDED_FOR=forwarded_for)


def test_clients_are_told_apart_by_x_forwarded_for(client, providers):
    providers()
    exhaust(client, "203.0.113.1")

    assert_error(post(client, payload={}, HTTP_X_FORWARDED_FOR="203.0.113.1"), 429, "rate_limited")
    # A different visitor behind the same proxy is still served.
    assert post(client, payload={}, HTTP_X_FORWARDED_FOR="203.0.113.2").status_code == 400


def test_a_forged_leading_entry_does_not_buy_a_new_bucket(client, providers):
    providers()
    exhaust(client, "203.0.113.1")

    # With one trusted proxy the client is the last entry; the proxy appended it.
    forged = post(client, payload={}, HTTP_X_FORWARDED_FOR="198.51.100.9, 203.0.113.1")

    assert_error(forged, 429, "rate_limited")


def test_without_the_header_the_socket_address_is_used(client, providers):
    providers()
    exhaust(client, "203.0.113.1")

    # No header: REMOTE_ADDR (127.0.0.1 in the test client), its own bucket.
    assert post(client, payload={}).status_code == 400
