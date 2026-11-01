"""Look up the forecast for a checkpoint's forecast hour."""

from datetime import datetime
from typing import Mapping

from .models import WeatherSample


def weather_at(series: Mapping[datetime, WeatherSample], hour: datetime) -> WeatherSample | None:
    """The sample for a UTC hour, or None when the series has no entry for it.

    None must become an unavailable checkpoint (risk.assess_risk does this),
    never a Low one. `hour` is normally checkpoints.forecast_hour(eta).
    """
    if hour.utcoffset() is None:
        raise ValueError("hour must be timezone-aware")
    return series.get(hour)
