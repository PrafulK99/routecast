"""Hour arithmetic shared by the analyze and heatmap services."""

from datetime import datetime, timezone

HEATMAP_HOURS = 49  # slider positions 0..48 hours after departure
NO_FORECAST_LEVEL = -1


def floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
