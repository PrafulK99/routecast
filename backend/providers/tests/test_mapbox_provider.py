import copy
import re

import httpx
import pytest

from providers.errors import NoRouteError, RoutingUnavailableError
from providers.fakes import InMemoryCache
from providers.interfaces import WARNING_MISSING_ANNOTATIONS, WARNING_ROUTE_FALLBACK, warning_few_routes
from providers.mapbox import MapboxRoutingProvider, parse_directions, via_offset_miles, without_duplicates

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
    """The recorded pair plus a third road 0.5 degrees of longitude away (never a duplicate)."""
    body = mapbox_body()
    third = copy.deepcopy(body["routes"][0])
    third["geometry"]["coordinates"] = [[lon + 0.5, lat] for lon, lat in third["geometry"]["coordinates"]]
    body["routes"].append(third)
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


def test_a_trip_beyond_the_distance_limit_is_no_route_not_a_routing_outage():
    # Real Mapbox answer for Los Angeles to Sydney: HTTP 422, code InvalidInput.
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            422, json={"code": "InvalidInput", "message": "Route exceeds maximum distance limitation"}
        )

    with pytest.raises(NoRouteError):
        get(make_provider(handler))

    assert len(calls) == 1  # retrying a trip that is too far would never help


def test_other_invalid_input_is_still_a_routing_failure():
    def handler(request):
        return httpx.Response(422, json={"code": "InvalidInput", "message": "Coordinate is invalid"})

    with pytest.raises(RoutingUnavailableError):
        get(make_provider(handler))


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
    # Positions 35% and 65% along the road; offsets 20% and 40% of ~104 miles (~20.7 and ~41.4 miles).
    near = sorted(abs(lon + 97.0) * 59.8 for lat, lon in vias if round(lat, 1) == round(30.0 + 0.35 * 1.5, 1))
    far = sorted(abs(lon + 97.0) * 59.8 for lat, lon in vias if round(lat, 1) == round(30.0 + 0.65 * 1.5, 1))
    assert near == [pytest.approx(20.7, abs=1.0)] * 2
    assert far == [pytest.approx(41.4, abs=1.5)] * 2
    assert sorted(v[1] < -97.0 for v in vias) == [False, False, True, True]


@pytest.mark.parametrize(
    "share, straight, expected",
    [
        (0.20, 104, 20.8),  # typical short trip: the share itself
        (0.20, 20, 10),  # tiny trip: the minimum
        (0.40, 1238, 495.2),  # long trip: far beyond the old 60-mile cap
        (0.40, 3000, 600),  # extreme trip: the maximum
    ],
)
def test_via_offset_is_a_share_of_the_straight_line_distance_within_limits(share, straight, expected):
    assert via_offset_miles(share, straight) == pytest.approx(expected)


def test_the_same_trip_always_gives_the_same_routes():
    first = fallback_provider(detour)[1].get_routes(ORIGIN, DESTINATION)
    second = fallback_provider(detour)[1].get_routes(ORIGIN, DESTINATION)

    assert [r.geometry for r in first.routes] == [r.geometry for r in second.routes]


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


def alternative(share):
    """A provider alternative that follows PRIMARY for `share` of its length, then leaves it."""
    keep = int(round(share * 20))
    on_road = [(30.0 + 1.5 * i / 20, -97.0) for i in range(keep + 1)]
    off_road = [(30.0 + 1.5 * i / 20, -97.0 - 0.5) for i in range(keep + 1, 21)]
    return on_road + off_road


def fine_primary():
    return [(30.0 + 1.5 * i / 20, -97.0) for i in range(21)]


def two_with_alternative(share):
    return directions_body([[fine_primary()], [alternative(share)]])


def test_an_identical_provider_route_is_a_duplicate_and_candidates_fill_the_slot():
    stub, provider = fallback_provider(detour, directions_body([[PRIMARY], [PRIMARY]]))

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 3
    assert WARNING_ROUTE_FALLBACK in result.warnings
    assert len(stub.requests) <= 5
    assert all(any(lon != -97.0 for _, lon in r.geometry) for r in result.routes[1:])  # real detours


def test_a_duplicate_with_no_good_candidates_leaves_one_route_and_a_notice():
    stub, provider = fallback_provider(lambda via: 500, directions_body([[PRIMARY], [PRIMARY]]))

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 1
    assert result.warnings == (warning_few_routes(1),)


def test_an_alternative_sharing_about_90_percent_is_kept():
    stub, provider = fallback_provider(lambda via: 500, two_with_alternative(0.90))

    assert len(provider.get_routes(ORIGIN, DESTINATION).routes) == 2


def test_an_alternative_sharing_about_97_percent_is_dropped():
    routes = without_duplicates(parse_directions(two_with_alternative(0.975))[0])

    assert len(routes) == 1


def test_an_alternative_overlapping_an_earlier_alternative_is_dropped_too():
    far = [(30.0 + 1.5 * i / 20, -97.5) for i in range(21)]
    body = directions_body([[fine_primary()], [far], [far]])

    assert len(without_duplicates(parse_directions(body)[0])) == 2


def test_dropping_a_duplicate_keeps_the_call_budget_at_five():
    stub, provider = fallback_provider(detour, directions_body([[PRIMARY], [PRIMARY]]))

    provider.get_routes(ORIGIN, DESTINATION)

    assert len(stub.base_calls) == 1
    assert len(stub.via_calls) == 4


def test_a_candidate_beyond_the_old_sixty_mile_cap_gives_a_third_route_on_a_long_trip():
    # A 1,000-mile north-south trip: a 60-mile sideways offset would stay on the highway, 40% (~400 mi) does not.
    origin, destination = (20.0, -97.0), (34.5, -97.0)
    road = [(20.0 + 0.5 * i, -97.0) for i in range(30)]

    def candidate(via):
        # Mapbox snaps any via point within 100 miles of the road back onto it; farther ones are real detours.
        if abs(via[1] + 97.0) * 59.8 < 100:
            return directions_body([[[origin, (27.0, -97.0)], [(27.0, -97.0), destination]]])
        return directions_body([[[origin, via], [via, destination]]])

    stub = Stub(directions_body([[road], [road]]), candidate)

    result = make_provider(stub).get_routes(origin, destination)

    assert len(result.routes) == 3
    assert max(abs(lon + 97.0) for r in result.routes for _, lon in r.geometry) * 59.8 > 100


def test_the_best_fit_candidate_wins_not_the_first_that_passes():
    # West candidates share 3 of 4 vertices' worth of road with the primary (passes the 0.80 gate narrowly);
    # east candidates are a clean detour. The first candidate in order is west, yet east must be chosen.
    def candidate(via):
        if west_of_route(via):
            return directions_body([[PRIMARY[:3], [PRIMARY[2], (31.3, -97.2), DESTINATION]]])
        return detour(via)

    stub, provider = fallback_provider(candidate)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 3
    assert max(lon for _, lon in result.routes[1].geometry) > -97.0  # the east detour, not the west near-copy


def test_a_silly_detour_is_rejected_even_when_it_is_the_only_different_road():
    def candidate(via):
        return directions_body([[[ORIGIN, (via[0], via[1] - 3.0)], [(via[0], via[1] - 3.0), DESTINATION]]])

    stub, provider = fallback_provider(candidate)

    result = provider.get_routes(ORIGIN, DESTINATION)

    assert len(result.routes) == 1


def test_mapbox_calls_never_exceed_five():
    stub, provider = fallback_provider(detour, directions_body([[PRIMARY], [PRIMARY]]))

    provider.get_routes(ORIGIN, DESTINATION)

    assert len(stub.requests) <= 5


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
