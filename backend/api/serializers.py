"""Request validation and the response schema, written once.

The response serializers are mirrored by the TypeScript types in
frontend/src/api/types.ts; a sample response from the tests is type-checked
against them in the frontend build.
"""

import math
from datetime import datetime, timedelta, timezone

from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from domain.constants import ALLOWED_INTERVALS_MILES, CORRIDOR_POINT_CAP, DEFAULT_INTERVAL_MILES, LEVEL_NAMES, Level
from domain.geo import haversine_miles
from services.analyze import TripRequest
from services.heatmap import HeatmapRequest

from .weather_payload import WeatherField

MIN_TRIP_MILES = 0.5
MAX_LOAD_WEIGHT_LB = 200_000
DEPARTURE_WINDOW = timedelta(days=7)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> datetime:
    """The clock for the departure window; tests replace it."""
    return datetime.now(timezone.utc)


# --- requests -------------------------------------------------------------------


class FiniteFloatField(serializers.FloatField):
    """FloatField that rejects NaN, infinity and booleans (DRF accepts "nan")."""

    def to_internal_value(self, data):
        if isinstance(data, bool):
            self.fail("invalid")
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            self.fail("invalid")
        return value


class AwareDateTimeField(serializers.DateTimeField):
    """ISO 8601 with a UTC offset. A time without one is rejected, not assumed UTC."""

    default_error_messages = {
        "invalid": "Use an ISO 8601 date and time with a UTC offset, e.g. 2026-11-02T14:00:00Z.",
        "naive": "The time needs a UTC offset, e.g. 2026-11-02T14:00:00Z.",
    }

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        try:
            parsed = parse_datetime(data)
        except ValueError:
            parsed = None
        if parsed is None:
            self.fail("invalid")
        if parsed.utcoffset() is None:
            self.fail("naive")
        return parsed.astimezone(timezone.utc)


class LatLonPairField(serializers.ListField):
    """A [lat, lon] pair within range."""

    child = FiniteFloatField()

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        if len(values) != 2:  # checked here: ListField's length validators run afterwards
            raise serializers.ValidationError("A point is a [latitude, longitude] pair.")
        lat, lon = values
        if not -90 <= lat <= 90:
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        if not -180 <= lon <= 180:
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return lat, lon


class PointSerializer(serializers.Serializer):
    lat = FiniteFloatField(min_value=-90, max_value=90)
    lon = FiniteFloatField(min_value=-180, max_value=180)
    label = serializers.CharField(required=False, allow_blank=True, max_length=200)


class DepartureAndLoadSerializer(serializers.Serializer):
    """The two fields both POST endpoints share."""

    departure_time = AwareDateTimeField()
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_WEIGHT_LB)

    def validate_departure_time(self, value):
        now = _now()
        earliest = now.replace(minute=0, second=0, microsecond=0)
        latest = now + DEPARTURE_WINDOW
        if not earliest <= value <= latest:
            raise serializers.ValidationError(
                f"Departure must be between {earliest:%Y-%m-%d %H:%M} UTC (the current hour) "
                f"and {latest:%Y-%m-%d %H:%M} UTC (7 days ahead)."
            )
        return value


class PlanRequestSerializer(DepartureAndLoadSerializer):
    """The trip. /api/plan takes exactly this; /api/analyze adds the optional weather."""

    origin = PointSerializer()
    destination = PointSerializer()
    checkpoint_interval_miles = serializers.ChoiceField(
        choices=ALLOWED_INTERVALS_MILES, default=DEFAULT_INTERVAL_MILES
    )

    def validate(self, attrs):
        origin, destination = attrs["origin"], attrs["destination"]
        distance = haversine_miles((origin["lat"], origin["lon"]), (destination["lat"], destination["lon"]))
        if distance < MIN_TRIP_MILES:
            raise serializers.ValidationError(
                {"destination": [f"The destination must be at least {MIN_TRIP_MILES} mile from the origin."]}
            )
        return attrs

    def create(self, validated_data):
        origin, destination = validated_data["origin"], validated_data["destination"]
        return TripRequest(
            origin=(origin["lat"], origin["lon"]),
            destination=(destination["lat"], destination["lon"]),
            departure_utc=validated_data["departure_time"],
            load_weight_lb=validated_data["load_weight_lb"],
            interval_miles=validated_data["checkpoint_interval_miles"],
        )


class AnalyzeRequestSerializer(PlanRequestSerializer):
    weather = WeatherField(required=False, allow_null=True)


class HeatmapRequestSerializer(DepartureAndLoadSerializer):
    points = serializers.ListField(child=LatLonPairField(), min_length=1, max_length=CORRIDOR_POINT_CAP)
    weather = WeatherField(required=False, allow_null=True)

    def create(self, validated_data):
        return HeatmapRequest(
            points=tuple(validated_data["points"]),
            departure_utc=validated_data["departure_time"],
            load_weight_lb=validated_data["load_weight_lb"],
        )


# --- responses ------------------------------------------------------------------


class RoundedFloatField(serializers.FloatField):
    """A float rounded to a fixed number of decimals, so JSON carries no float noise."""

    def __init__(self, decimals, **kwargs):
        self.decimals = decimals
        super().__init__(**kwargs)

    def to_representation(self, value):
        return round(float(value), self.decimals)


def _time_field(**kwargs):
    return serializers.DateTimeField(format=TIME_FORMAT, **kwargs)


def _level_name(level):
    return None if level is None else LEVEL_NAMES[Level(level)]


class RiskSerializer(serializers.Serializer):
    level = serializers.IntegerField(allow_null=True)
    level_name = serializers.SerializerMethodField()
    factor = serializers.CharField(allow_null=True)
    wind_level = serializers.IntegerField(allow_null=True)
    rain_level = serializers.IntegerField(allow_null=True)
    snow_level = serializers.IntegerField(allow_null=True)
    load_rule_applied = serializers.BooleanField()

    def get_level_name(self, risk):
        return _level_name(risk.level)


class CheckpointSerializer(serializers.Serializer):
    index = serializers.IntegerField(source="checkpoint.index")
    mile = RoundedFloatField(2, source="checkpoint.mile")
    lat = RoundedFloatField(5, source="checkpoint.lat")
    lon = RoundedFloatField(5, source="checkpoint.lon")
    eta = _time_field(source="checkpoint.eta_utc")
    forecast_hour = _time_field(source="checkpoint.forecast_hour_utc")
    wind_mph = RoundedFloatField(1, source="weather.wind_mph", allow_null=True)
    rain_in_hr = RoundedFloatField(3, source="weather.rain_in_hr", allow_null=True)
    snow_in_hr = RoundedFloatField(3, source="weather.snow_in_hr", allow_null=True)
    segment_mi = RoundedFloatField(2, source="checkpoint.segment_mi")
    status = serializers.CharField(source="risk.status")
    risk = RiskSerializer()


class SummarySerializer(serializers.Serializer):
    miles_by_level = serializers.SerializerMethodField()
    avg_risk = RoundedFloatField(3, allow_null=True)
    worst_level = serializers.IntegerField(allow_null=True)
    worst_level_name = serializers.SerializerMethodField()
    coverage_pct = RoundedFloatField(1)
    blocked = serializers.BooleanField()

    def get_miles_by_level(self, summary):
        return {level.name.lower(): round(summary.miles_by_level[level], 1) for level in Level}

    def get_worst_level_name(self, summary):
        return _level_name(summary.worst_level)


class RouteSerializer(serializers.Serializer):
    id = serializers.CharField(source="route.id")
    label = serializers.CharField(source="route.label")
    distance_mi = RoundedFloatField(1, source="route.distance_mi")
    duration_s = serializers.SerializerMethodField()
    departure_time = _time_field(source="departure_utc")
    arrival_time = _time_field(source="arrival_utc")
    geometry = serializers.SerializerMethodField()
    summary = SummarySerializer()
    checkpoints = CheckpointSerializer(many=True)

    def get_duration_s(self, result):
        """Truck-adjusted seconds."""
        return round(result.summary.duration_s)

    def get_geometry(self, result):
        """GeoJSON LineString, [lon, lat] order, simplified for display."""
        return {
            "type": "LineString",
            "coordinates": [[round(lon, 5), round(lat, 5)] for lat, lon in result.display_geometry],
        }


class SortKeySerializer(serializers.Serializer):
    """The five ranking keys of a RankingEntry, in the order they are compared."""

    no_travel_mi = serializers.SerializerMethodField()
    severe_mi = serializers.SerializerMethodField()
    high_mi = serializers.SerializerMethodField()
    avg_risk = serializers.SerializerMethodField()
    duration_s = serializers.SerializerMethodField()

    def get_no_travel_mi(self, entry):
        return entry.sort_key[0]

    def get_severe_mi(self, entry):
        return entry.sort_key[1]

    def get_high_mi(self, entry):
        return entry.sort_key[2]

    def get_avg_risk(self, entry):
        return entry.sort_key[3]  # None when the route had no forecast data

    def get_duration_s(self, entry):
        return round(entry.sort_key[4])


class RankingEntrySerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    route_id = serializers.CharField()
    sort_key = SortKeySerializer(source="*")


class RecommendationSerializer(serializers.Serializer):
    route_id = serializers.CharField()
    reasons = serializers.ListField(child=serializers.CharField())
    all_blocked = serializers.BooleanField()
    ranking = RankingEntrySerializer(many=True)


class MetaSerializer(serializers.Serializer):
    request_id = serializers.CharField()
    interval_miles = serializers.IntegerField()
    truck_duration_factor = serializers.FloatField()
    forecast_source = serializers.CharField()
    warnings = serializers.ListField(child=serializers.CharField())


class AnalyzeResponseSerializer(serializers.Serializer):
    meta = MetaSerializer()
    routes = RouteSerializer(many=True)
    recommendation = RecommendationSerializer()
    corridor_points = serializers.SerializerMethodField()
    corridor_cells = serializers.SerializerMethodField()

    def get_corridor_points(self, result):
        """[lat, lon] pairs, ready to post to /api/heatmap."""
        return [[round(lat, 5), round(lon, 5)] for lat, lon in result.corridor_points]

    def get_corridor_cells(self, result):
        """[lat, lon] grid cells of the corridor points: the weather the heatmap needs."""
        return [[lat, lon] for lat, lon in result.corridor_cells]


class PlanResponseSerializer(serializers.Serializer):
    cells = serializers.SerializerMethodField()
    window = serializers.SerializerMethodField()

    def get_cells(self, plan):
        """[lat, lon] grid cells of every checkpoint of every route: the weather to fetch."""
        return [[lat, lon] for lat, lon in plan.cells]

    def get_window(self, plan):
        return {
            "first_hour": plan.first_hour.strftime(TIME_FORMAT),
            "last_hour": plan.last_hour.strftime(TIME_FORMAT),
        }


class HeatmapPointSerializer(serializers.Serializer):
    lat = RoundedFloatField(5)
    lon = RoundedFloatField(5)
    levels = serializers.ListField(child=serializers.IntegerField())


class HeatmapResponseSerializer(serializers.Serializer):
    start_hour = _time_field()
    hours = serializers.IntegerField()
    points = HeatmapPointSerializer(many=True)
