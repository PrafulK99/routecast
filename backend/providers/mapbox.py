"""Mapbox Directions adapter with the via-point fallback for a third route."""

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Callable

import httpx

from domain.checkpoints import cumulative_totals
from domain.geo import haversine_miles, overlap_fraction, perpendicular_offsets
from domain.models import Route

from .constants import (
    MAPBOX_DIRECTIONS_URL,
    DISTANCE_LIMIT_MESSAGE,
    MAPBOX_TIMEOUT_S,
    MAX_ROUTES,
    METERS_PER_MILE,
    NO_ROUTE_CODES,
    OVERLAP_SPACING_MILES,
    OVERLAP_TOLERANCE_MILES,
    PROVIDER_DUPLICATE_OVERLAP,
    RETRY_BACKOFF_S,
    ROUTE_CACHE_TTL_S,
    VIA_CANDIDATES,
    VIA_LENGTH_PENALTY,
    VIA_MAX_LENGTH_RATIO,
    VIA_MAX_OVERLAP,
    VIA_MAX_WORKERS,
    VIA_OFFSET_MAX_MILES,
    VIA_OFFSET_MIN_MILES,
)
from .errors import NoRouteError, ProviderError, RoutingUnavailableError
from .interfaces import (
    WARNING_MISSING_ANNOTATIONS,
    WARNING_ROUTE_FALLBACK,
    Cache,
    LatLon,
    RoutingResult,
    warning_few_routes,
)

_PROVIDER = "mapbox"


def _cache_key(waypoints: list[LatLon]) -> str:
    text = _PROVIDER + "|" + ";".join(f"{lat:.5f},{lon:.5f}" for lat, lon in waypoints)
    return "route:" + hashlib.sha256(text.encode()).hexdigest()


def _annotation_segments(raw: dict, vertex_count: int) -> tuple[list[float], list[float]] | None:
    """Per-segment (miles, seconds) from the leg annotations, joined across legs.
    None when they are missing or do not match the geometry (one value per segment)."""
    meters: list[float] = []
    seconds: list[float] = []
    for leg in raw.get("legs", []):
        annotation = leg.get("annotation") or {}
        meters += annotation.get("distance") or []
        seconds += annotation.get("duration") or []
    expected = vertex_count - 1
    if len(meters) != expected or len(seconds) != expected:
        return None
    if any(value is None for value in (*meters, *seconds)):
        return None
    return [m / METERS_PER_MILE for m in meters], [float(s) for s in seconds]


def _proportional_segments(
    geometry: tuple[LatLon, ...], raw: dict
) -> tuple[list[float], list[float]]:
    """Spread the route's total distance and duration over its segments by length."""
    lengths = [haversine_miles(a, b) for a, b in zip(geometry, geometry[1:])]
    total = sum(lengths)
    if total > 0:
        shares = [length / total for length in lengths]
    else:
        shares = [1 / len(lengths)] * len(lengths)
    return (
        [share * raw["distance"] / METERS_PER_MILE for share in shares],
        [share * raw["duration"] for share in shares],
    )


def parse_directions(body: dict) -> tuple[list[Route], list[str]]:
    """Routes and warnings from a Directions response body. Pure; no network.

    Raises NoRouteError when Mapbox found no route.
    """
    code = body.get("code")
    if code in NO_ROUTE_CODES or (code == "Ok" and not body.get("routes")):
        raise NoRouteError("No drivable route was found between these points.")
    if code != "Ok":
        raise RoutingUnavailableError(f"Mapbox returned an unexpected response ({code}).")

    routes = []
    warnings: list[str] = []
    for index, raw in enumerate(body["routes"]):
        # GeoJSON is (lon, lat); the domain uses (lat, lon).
        geometry = tuple((lat, lon) for lon, lat, *_ in raw["geometry"]["coordinates"])
        segments = _annotation_segments(raw, len(geometry))
        if segments is None:
            segments = _proportional_segments(geometry, raw)
            if WARNING_MISSING_ANNOTATIONS not in warnings:
                warnings.append(WARNING_MISSING_ANNOTATIONS)
        cumulative_mi, cumulative_s = cumulative_totals(*segments)
        routes.append(
            Route(f"route-{index + 1}", f"Route {chr(65 + index)}", geometry, cumulative_mi, cumulative_s)
        )
    return routes, warnings


def via_offset_miles(share: float, straight_miles: float) -> float:
    """How far a candidate via point sits beside the route: a share of the straight-line trip
    distance, kept within limits (a fixed few miles would leave long trips on the same highway)."""
    return min(max(share * straight_miles, VIA_OFFSET_MIN_MILES), VIA_OFFSET_MAX_MILES)


def _overlap(route: Route, other: Route) -> float:
    return overlap_fraction(route, other, OVERLAP_SPACING_MILES, OVERLAP_TOLERANCE_MILES)


def without_duplicates(routes: list[Route]) -> list[Route]:
    """Drop a provider route that lies almost entirely on a route already kept
    (PROVIDER_DUPLICATE_OVERLAP or more), so a via-point candidate can take its place."""
    kept: list[Route] = []
    for route in routes:
        if not any(_overlap(route, other) >= PROVIDER_DUPLICATE_OVERLAP for other in kept):
            kept.append(route)
    return kept


class MapboxRoutingProvider:
    def __init__(
        self,
        token: str,
        client: httpx.Client,
        cache: Cache,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._token = token
        self._client = client
        self._cache = cache
        self._sleep = sleep

    @classmethod
    def from_env(cls, client: httpx.Client, cache: Cache) -> "MapboxRoutingProvider":
        token = os.environ.get("MAPBOX_API_TOKEN")
        if not token:
            raise RuntimeError("MAPBOX_API_TOKEN is not set")
        return cls(token, client, cache)

    def get_routes(self, origin: LatLon, destination: LatLon) -> RoutingResult:
        routes, warnings = parse_directions(self._directions([origin, destination], alternatives=True))
        routes = without_duplicates(routes)
        if len(routes) < MAX_ROUTES:
            routes, warnings = self._add_via_routes(origin, destination, routes, warnings)
        routes = [
            replace(route, id=f"route-{i + 1}", label=f"Route {chr(65 + i)}")
            for i, route in enumerate(routes)
        ]
        if len(routes) < MAX_ROUTES:
            warnings.append(warning_few_routes(len(routes)))
        return RoutingResult(tuple(routes), tuple(warnings))

    def _add_via_routes(
        self, origin: LatLon, destination: LatLon, routes: list[Route], warnings: list[str]
    ) -> tuple[list[Route], list[str]]:
        primary = routes[0]
        straight = haversine_miles(origin, destination)
        # Fixed order (each setting: left, then right) keeps results deterministic.
        via_points = [
            point
            for position, share in VIA_CANDIDATES
            for point in perpendicular_offsets(primary, position, via_offset_miles(share, straight))
        ]
        with ThreadPoolExecutor(max_workers=VIA_MAX_WORKERS) as pool:
            fetched = list(pool.map(lambda via: self._via_route(origin, via, destination), via_points))

        # Only candidates not absurdly longer than the primary are worth comparing.
        remaining = {
            index: candidate
            for index, candidate in enumerate(fetched)
            if candidate is not None and candidate[0].distance_mi <= VIA_MAX_LENGTH_RATIO * primary.distance_mi
        }
        kept = list(routes)
        warnings = list(warnings)
        used_fallback = False
        overlaps: dict[tuple[int, int], float] = {}  # (candidate, kept route) -> overlap, each worked out once
        while len(kept) < MAX_ROUTES and remaining:
            scored = []
            for index, (route, _) in remaining.items():
                worst = max(overlaps.setdefault((index, id(other)), _overlap(route, other)) for other in kept)
                if worst <= VIA_MAX_OVERLAP:
                    ratio = route.distance_mi / primary.distance_mi
                    # Best fit: the most different road, without a needless detour; ties to the shorter, then the earlier.
                    scored.append((worst + VIA_LENGTH_PENALTY * (ratio - 1), route.distance_mi, index))
            if not scored:
                break
            chosen = min(scored)[2]
            route, route_warnings = remaining.pop(chosen)
            kept.append(route)
            used_fallback = True
            warnings += [w for w in route_warnings if w not in warnings]
        if used_fallback:
            warnings.append(WARNING_ROUTE_FALLBACK)
        return kept, warnings

    def _via_route(
        self, origin: LatLon, via: LatLon, destination: LatLon
    ) -> tuple[Route, list[str]] | None:
        """One candidate route through `via`, or None if Mapbox cannot make one.
        A failed candidate is never fatal."""
        try:
            # Mapbox offers alternatives only for two-waypoint requests.
            body = self._directions([origin, via, destination], alternatives=False)
            routes, warnings = parse_directions(body)
        except ProviderError:
            return None
        return routes[0], warnings

    def _directions(self, waypoints: list[LatLon], alternatives: bool) -> dict:
        key = _cache_key(waypoints)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        body = self._request(waypoints, alternatives)
        # Only a success or a definitive no-route answer is worth reusing.
        if body.get("code") == "Ok" or body.get("code") in NO_ROUTE_CODES:
            self._cache.set(key, body, ROUTE_CACHE_TTL_S)
        return body

    def _request(self, waypoints: list[LatLon], alternatives: bool) -> dict:
        coordinates = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
        params = {
            "alternatives": str(alternatives).lower(),
            "geometries": "geojson",
            "overview": "full",
            "annotations": "distance,duration",
            "steps": "false",
            "access_token": self._token,
        }
        for attempt in range(2):
            if attempt:
                self._sleep(RETRY_BACKOFF_S)
            try:
                response = self._client.get(
                    f"{MAPBOX_DIRECTIONS_URL}/{coordinates}", params=params, timeout=MAPBOX_TIMEOUT_S
                )
            except httpx.HTTPError:
                continue  # transport error or timeout: retry once
            status = response.status_code
            if status == 429 or status >= 500:
                continue
            if status in (401, 403):
                raise RoutingUnavailableError("Mapbox rejected the API token.")
            try:
                body = response.json()
            except ValueError:
                continue
            if body.get("code") in NO_ROUTE_CODES:
                return body  # parse_directions turns this into NoRouteError
            if status == 422 and DISTANCE_LIMIT_MESSAGE in str(body.get("message", "")).lower():
                return {"code": "NoRoute", "routes": []}  # too far to route: no drivable route
            if status != 200:
                raise RoutingUnavailableError(f"Mapbox rejected the request (HTTP {status}).")
            return body
        raise RoutingUnavailableError("Mapbox did not respond after one retry.")
