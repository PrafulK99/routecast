"""Grid cells, corridor points and the route geometry used by the providers.

Points are (lat, lon) pairs. The antimeridian and the poles are not supported.
"""

import math
from typing import Iterable

from .checkpoints import interpolate_at_mile, sample_miles
from .constants import (
    CORRIDOR_POINT_CAP,
    CORRIDOR_SPACING_GROWTH,
    CORRIDOR_SPACING_MILES,
    GRID_DECIMALS,
)
from .models import Route

LatLon = tuple[float, float]

EARTH_RADIUS_MILES = 3958.7613
MILES_PER_DEGREE = math.radians(1) * EARTH_RADIUS_MILES
# overlap_fraction measures against the other route resampled this finely
# (as a fraction of the tolerance), so the sampling error stays under a tenth of it.
_OVERLAP_RESAMPLE_FRACTION = 0.25


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    """Round to the 0.1 degree grid so nearby points share one weather lookup."""
    # Adding 0.0 turns -0.0 into 0.0 so the cell prints and hashes one way.
    return round(lat, GRID_DECIMALS) + 0.0, round(lon, GRID_DECIMALS) + 0.0


def haversine_miles(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in miles."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


def bearing_degrees(a: LatLon, b: LatLon) -> float:
    """Initial compass bearing from a to b, 0 (north) to 360, clockwise."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360


def offset_point(point: LatLon, bearing: float, miles: float) -> LatLon:
    """The point reached by travelling `miles` from `point` on a compass bearing."""
    lat1, lon1 = map(math.radians, point)
    theta = math.radians(bearing)
    delta = miles / EARTH_RADIUS_MILES
    lat2 = math.asin(
        math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(theta)
    )
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180


def perpendicular_offsets(
    route: Route, fraction: float, miles: float, window_miles: float = 2.0
) -> tuple[LatLon, LatLon]:
    """(left, right) points `miles` to either side of the route at `fraction` of
    its length. The local direction is taken over `window_miles` either side, so
    a wiggle in the geometry does not tilt the offset."""
    mile = fraction * route.distance_mi
    lat, lon, _ = interpolate_at_mile(route, mile)
    behind = interpolate_at_mile(route, mile - window_miles)[:2]
    ahead = interpolate_at_mile(route, mile + window_miles)[:2]
    heading = bearing_degrees(behind, ahead)
    return (
        offset_point((lat, lon), heading - 90, miles),
        offset_point((lat, lon), heading + 90, miles),
    )


def _projected(point: LatLon) -> tuple[float, float]:
    """Local flat-earth miles (x east, y north); only meant for distances of a few miles."""
    lat, lon = point
    return lon * math.cos(math.radians(lat)) * MILES_PER_DEGREE, lat * MILES_PER_DEGREE


def overlap_fraction(
    route: Route, other: Route, spacing_miles: float, tolerance_miles: float
) -> float:
    """Share of `route`, sampled every `spacing_miles`, within `tolerance_miles`
    of `other`: 1.0 for the same road, 0.0 for routes that never come close."""
    step = tolerance_miles * _OVERLAP_RESAMPLE_FRACTION
    buckets: dict[tuple[int, int], list[LatLon]] = {}
    for mile in sample_miles(other.distance_mi, step):
        point = interpolate_at_mile(other, mile)[:2]
        x, y = _projected(point)
        buckets.setdefault((math.floor(x / tolerance_miles), math.floor(y / tolerance_miles)), []).append(point)

    def is_near(point: LatLon) -> bool:
        x, y = _projected(point)
        cx, cy = math.floor(x / tolerance_miles), math.floor(y / tolerance_miles)
        return any(
            haversine_miles(point, candidate) <= tolerance_miles
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for candidate in buckets.get((cx + dx, cy + dy), ())
        )

    samples = [interpolate_at_mile(route, mile)[:2] for mile in sample_miles(route.distance_mi, spacing_miles)]
    return sum(is_near(point) for point in samples) / len(samples)


def _distance_to_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify_polyline(points: list[LatLon], tolerance_miles: float, max_points: int) -> list[LatLon]:
    """Douglas-Peucker: drop vertices closer than `tolerance_miles` to the line
    through their neighbours, then, if more than `max_points` remain, keep only
    the most significant ones. The first and last vertex are always kept and the
    order is unchanged.

    Distances are measured on a flat projection around the route's middle
    latitude, which is accurate to a few percent over a continental route and
    far inside what a 50 m display tolerance needs. Iterative, so a 13,000
    vertex route cannot hit the recursion limit.
    """
    if max_points < 2:
        raise ValueError("max_points must be at least 2")
    count = len(points)
    if count <= 2:
        return list(points)

    lat0 = sum(lat for lat, _ in points) / count
    lon0 = points[0][1]
    x_scale = math.cos(math.radians(lat0)) * MILES_PER_DEGREE
    flat = [((lon - lon0) * x_scale, lat * MILES_PER_DEGREE) for lat, lon in points]

    # importance[i] is how far vertex i stood from the line when it was chosen.
    importance: dict[int, float] = {0: math.inf, count - 1: math.inf}
    pending = [(0, count - 1)]
    while pending:
        first, last = pending.pop()
        farthest, farthest_distance = -1, tolerance_miles
        for i in range(first + 1, last):
            distance = _distance_to_segment(flat[i], flat[first], flat[last])
            if distance >= farthest_distance:
                farthest, farthest_distance = i, distance
        if farthest == -1:
            continue
        importance[farthest] = farthest_distance
        pending.append((first, farthest))
        pending.append((farthest, last))

    kept = sorted(importance, key=lambda i: (-importance[i], i))[:max_points]
    return [points[i] for i in sorted(kept)]


def _sample_routes(routes: Iterable[Route], spacing_miles: float) -> list[tuple[float, float]]:
    seen = set()
    points = []
    for route in routes:
        for mile in sample_miles(route.distance_mi, spacing_miles):
            lat, lon, _ = interpolate_at_mile(route, mile)
            cell = grid_cell(lat, lon)
            if cell not in seen:
                seen.add(cell)
                points.append((lat, lon))
    return points


def corridor_points(
    routes: Iterable[Route],
    spacing_miles: float = CORRIDOR_SPACING_MILES,
    cap: int = CORRIDOR_POINT_CAP,
) -> list[tuple[float, float]]:
    """(lat, lon) points along every route, one per grid cell, at most `cap`.

    Spacing grows until the result fits; a route shorter than the spacing still
    yields its start and end.
    """
    routes = list(routes)
    longest = max((route.distance_mi for route in routes), default=0.0)
    while True:
        points = _sample_routes(routes, spacing_miles)
        if len(points) <= cap:
            return points
        if spacing_miles > longest:
            return points[:cap]
        spacing_miles *= CORRIDOR_SPACING_GROWTH
