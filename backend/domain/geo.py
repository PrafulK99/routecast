"""Grid cells and corridor points shared by the weather cache and the heatmap."""

from typing import Iterable

from .checkpoints import interpolate_at_mile, sample_miles
from .constants import (
    CORRIDOR_POINT_CAP,
    CORRIDOR_SPACING_GROWTH,
    CORRIDOR_SPACING_MILES,
    GRID_DECIMALS,
)
from .models import Route


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    """Round to the 0.1 degree grid so nearby points share one weather lookup."""
    # Adding 0.0 turns -0.0 into 0.0 so the cell prints and hashes one way.
    return round(lat, GRID_DECIMALS) + 0.0, round(lon, GRID_DECIMALS) + 0.0


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
