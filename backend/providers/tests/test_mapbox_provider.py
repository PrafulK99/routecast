import re

import httpx
import pytest

from providers.errors import NoRouteError, RoutingUnavailableError
from providers.fakes import InMemoryCache
from providers.interfaces import WARNING_MISSING_ANNOTATIONS, WARNING_ROUTE_FALLBACK, warning_few_routes
from providers.mapbox import MapboxRoutingProvider

from .helpers import directions_body, json_response, mapbox_body, waypoints

TOKEN = "pk.test-secret-token"
ORIGIN = (30.0, -97.0)
DESTINATION = (31.5, -97.0)  # about 104 miles due north
PRIMARY = [(30.0 + 0.5 * i, -97.0) for i in range(4)]  # same road, with vertices


class Stub:
    """A Mapbox stand-in. Two-waypoint requests get `base`; requests with a via
    point get `candidate(via)`, which may return a body, a status code, or raise."""

    def __init__(self, base, candidate=None):
        self.base = base
        self.candidate = candidate
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        points = waypoints(request)
        result = self.base if len(points) == 2 else self.candidate(points[1])
        if isinstance(result, Exception):
            raise result
        if isinstance(result, int):
            return httpx.Response(result, json={"message": "stub failure"})
        return json_response(result)

    @property
    def base_calls(self):
        return [r for r in self.requests if len(waypoints(r)) == 2]

    @property
    def via_calls(self):
        return [r for r in self.requests if len(waypoints(r)) == 3]


def make_provider(handler, cache=None, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MapboxRoutingProvider(
        TOKEN, client, cache if cache is not None else InMemoryCache(),
        sleep=(sleeps if sleeps is not None else []).append,
    )  # fmt: skip


def three_routes():
    body = mapbox_body()
    body["routes"].append(body["routes"][0])
    return body


def detour(via):
    """A route origin -> via -> destination, as two legs."""
    return directions_body([[[ORIGIN, via], [via, DESTINATION]]])


def west_of_route(via):
    return via[1] < -97.0


def get(provider, origin=(39.0997, -94.5786), destination=(38.627, -90.1994)):
    return provider.get_routes(origin, destination)


# --- request, retry and errors ------------------------------------------------


def test_request_asks_for_exactly_the_specified_route_data():
    stub = Stub(three_routes())

    get(make_provider(stub))

    request = stub.requests[0]
    assert request.url.path == "/directions/v5/mapbox/driving/-94.5786,39.0997;-90.1994,38.627"
    assert dict(request.url.params) == {
        "alternatives": "true",
        "geometries": "geojson",
        "overview": "full",
        "annotations": "distance,duration",
        "steps": "false",
        "access_token": TOKEN,
    }


def test_three_routes_from_mapbox_need_no_fallback():
    stub = Stub(three_routes())

    result = get(make_provider(stub))

    assert len(stub.requests) == 1
    assert [r.label for r in result.routes] == ["Route A", "Route B", "Route C"]
    assert result.warnings == ()


def test_one_retry_after_a_server_error_then_success():
    responses = iter([httpx.Response(503), json_response(three_routes())])
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        return next(responses)

    provider = make_provider(handler, sleeps=sleeps)

    result = get(provider)

    assert len(calls) == 2
    assert sleeps == [0.5]
    assert len(result.routes) == 3


@pytest.mark.parametrize("failure", [500, 503, 429, httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
def test_failing_twice_raises_a_routing_error_without_the_token(failure):
    stub = Stub(failure)
    sleeps = []

    with pytest.raises(RoutingUnavailableError) as raised:
        get(make_provider(stub, sleeps=sleeps))

    assert len(stub.requests) == 2  # the request and one retry, no more
    assert sleeps == [0.5]
    assert TOKEN not in str(raised.value) and "http" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


@pytest.mark.parametrize("status", [401, 403, 422])
def test_client_errors_are_not_retried(status):
    stub = Stub(status)

    with pytest.raises(RoutingUnavailableError):
        get(make_provider(stub))

    assert len(stub.requests) == 1


def test_invalid_json_is_retried_once():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"<html>gateway</html>")

    with pytest.raises(RoutingUnavailableError):
        get(make_provider(handler))

    assert len(calls) == 2


@pytest.mark.parametrize("status", [200, 404])
def test_no_route_raises_no_route_and_skips_the_fallback(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"code": "NoRoute", "routes": []})

    with pytest.raises(NoRouteError):
        get(make_provider(handler))

    assert len(calls) == 1


def test_token_is_required_by_from_env(monkeypatch):
    monkeypatch.delenv("MAPBOX_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        MapboxRoutingProvider.from_env(httpx.Client(), InMemoryCache())

    monkeypatch.setenv("MAPBOX_API_TOKEN", TOKEN)
    assert MapboxRoutingProvider.from_env(httpx.Client(), InMemoryCache())._token == TOKEN


# --- cache ----------------------------------------------------------------------


def test_raw_responses_are_cached_for_ten_minutes_by_trip():
    stub = Stub(three_routes())
    cache = InMemoryCache()
    provider = make_provider(stub, cache)

    first = get(provider)
    second = get(provider)

    assert len(stub.requests) == 1
    assert second == first
    (key,) = cache.values
    assert re.fullmatch(r"route:[0-9a-f]{64}", key)
    assert cache.timeouts[key] == 600
    assert TOKEN not in key


def test_a_different_trip_is_a_different_cache_entry():
    stub = Stub(three_routes())
    provider = make_provider(stub)

    get(provider)
    get(provider, destination=(38.0, -90.0))

    assert len(stub.requests) == 2


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("boom"), httpx.Response(500), httpx.Response(429)],
    ids=["transport error", "5xx", "429"],
)
def test_failures_are_never_cached(failure):
    # The request and its retry both fail; the next call must go to the network again.
    results = iter([failure, failure, json_response(three_routes())])
    calls = []
    cache = InMemoryCache()

    def handler(request):
        calls.append(request)
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    provider = make_provider(handler, cache)

    with pytest.raises(RoutingUnavailableError):
        get(provider)
    assert cache.values == {}
    assert len(calls) == 2

    assert len(get(provider).routes) == 3
    assert len(calls) == 3


def test_a_200_with_an_unexpected_code_is_not_cached():
    results = iter([{"code": "ProfileNotFound"}, three_routes()])
    calls = []
    cache = InMemoryCache()

    def handler(request):
        calls.append(request)
        return json_response(next(results))

    provider = make_provider(handler, cache)

    with pytest.raises(RoutingUnavailableError):
        get(provider)
    assert cache.values == {}

    assert len(get(provider).routes) == 3
    assert len(calls) == 2


@pytest.mark.parametrize("body", [{"code": "NoRoute", "routes": []}, {"code": "Ok", "routes": []}])
def test_a_definitive_no_route_answer_is_cached(body):
    calls = []

    def handler(request):
        calls.append(request)
        return json_response(body)

    provider = make_provider(handler)

    for _ in range(2):
        with pytest.raises(NoRouteError):
            get(provider)

    assert len(calls) == 1


# --- via-point fallback ---------------------------------------------------------


def primary_only():
    return directions_body([[PRIMARY]])


def fallback_provider(candidate, base=None):
    stub = Stub(base or primary_only(), candidate)
    return stub, make_provider(stub)


def test_via_fallback_fills_the_third_route():
    stub, provider = fallback_provider(detour)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert [(r.id, r.label) for r in result.routes] == [
        ("route-1", "Route A"), ("route-2", "Route B"), ("route-3", "Route C"),
    ]  # fmt: skip
    assert WARNING_ROUTE_FALLBACK in result.warnings
    assert not any("could be found" in w for w in result.warnings)
    assert len(stub.base_calls) == 1


def test_all_four_candidates_are_requested_through_offset_points():
    stub, provider = fallback_provider(detour)

    provider.get_routes(ORIGIN, DESTINATION)

    vias = [waypoints(r)[1] for r in stub.via_calls]
    assert len(vias) == 4
    # Offset is 20% of ~104 miles = ~20.7 miles, at 35% and 65% along the road.
    expected_lats = {round(30.0 + 0.35 * 1.5, 1), round(30.0 + 0.65 * 1.5, 1)}
    assert {round(v[0], 1) for v in vias} == expected_lats
    assert sorted(v[1] < -97.0 for v in vias) == [False, False, True, True]
    for lat, lon in vias:
        assert abs(lon + 97.0) * 59.8 == pytest.approx(20.7, abs=1.0)  # ~59.8 mi per degree of lon here


def test_candidates_keep_a_fixed_order_left_before_right():
    stub, provider = fallback_provider(detour)

    result = provider.get_routes(ORIGIN, DESTINATION)

    # The first two candidates in order are left (west) then right (east) at 35%.
    assert min(lon for _, lon in result.routes[1].geometry) < -97.0
    assert max(lon for _, lon in result.routes[2].geometry) > -97.0


def test_a_candidate_more_than_1_5_times_the_primary_is_dropped():
    def candidate(via):
        return detour((via[0], via[1] - 2.0)) if west_of_route(via) else detour(via)

    stub, provider = fallback_provider(candidate)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 3
    assert all(r.distance_mi <= 1.5 * result.routes[0].distance_mi for r in result.routes)
    assert all(max(lon for _, lon in r.geometry) >= -97.0 for r in result.routes[1:])


def test_candidates_hugging_the_primary_are_dropped():
    def candidate(via):
        return directions_body([[PRIMARY[:3], PRIMARY[2:]]])

    stub, provider = fallback_provider(candidate)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 1
    assert WARNING_ROUTE_FALLBACK not in result.warnings
    assert result.warnings == (warning_few_routes(1),)


def test_a_candidate_overlapping_a_kept_candidate_is_dropped():
    # Both west candidates return the very same road, so only one may be kept;
    # the east candidates fail.
    shared = detour((30.75, -97.3))
    stub, provider = fallback_provider(lambda via: shared if west_of_route(via) else 422)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 2
    assert len(stub.via_calls) == 4


def test_stops_at_three_routes_but_still_asks_for_all_candidates():
    stub, provider = fallback_provider(detour)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 3
    assert len(stub.via_calls) == 4


def test_failing_candidates_are_skipped_not_fatal():
    def candidate(via):
        if west_of_route(via):
            return 500  # retried once, then skipped
        return detour(via)

    stub, provider = fallback_provider(candidate)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 3
    assert all(max(lon for _, lon in r.geometry) >= -97.0 for r in result.routes)


def test_a_candidate_with_no_route_is_skipped():
    def candidate(via):
        return {"code": "NoSegment", "routes": []} if west_of_route(via) else detour(via)

    stub, provider = fallback_provider(candidate)

    assert len(provider.get_routes(ORIGIN, DESTINATION).routes) == 3


def test_every_candidate_failing_leaves_what_exists_with_a_notice():
    stub, provider = fallback_provider(lambda via: 500)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 1
    assert result.warnings == (warning_few_routes(1),)


def test_two_provider_routes_get_one_fallback_route():
    base = directions_body([[PRIMARY], [[(30.0, -97.0), (30.75, -97.02), (31.5, -97.0)]]])
    stub, provider = fallback_provider(detour, base)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 3
    assert result.routes[1].geometry[1] == (30.75, -97.02)  # provider route kept in place


def test_routes_returned_by_the_provider_are_never_filtered():
    # Two identical routes straight from Mapbox are both kept; only candidates are filtered.
    base = directions_body([[PRIMARY], [PRIMARY]])
    stub, provider = fallback_provider(lambda via: 500, base)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 2
    assert result.warnings == (warning_few_routes(2),)


def test_candidate_with_missing_annotations_adds_its_warning_when_kept():
    def candidate(via):
        body = detour(via)
        for leg in body["routes"][0]["legs"]:
            del leg["annotation"]
        return body

    stub, provider = fallback_provider(candidate)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert WARNING_MISSING_ANNOTATIONS in result.warnings
    assert result.warnings.count(WARNING_MISSING_ANNOTATIONS) == 1


def test_a_failing_primary_request_never_starts_the_fallback():
    stub, provider = fallback_provider(detour, base=500)

    with pytest.raises(RoutingUnavailableError):
        provider.get_routes(ORIGIN, DESTINATION)

    assert stub.via_calls == []


def test_the_token_is_sent_on_every_call_but_never_cached():
    stub = Stub(primary_only(), detour)
    cache = InMemoryCache()

    make_provider(stub, cache).get_routes(ORIGIN, DESTINATION)

    assert all(r.url.params["access_token"] == TOKEN for r in stub.requests)
    assert TOKEN not in repr(cache.values.keys())
