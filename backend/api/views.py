from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from services import container
from services.analyze import analyze_trip
from providers.supplied import SuppliedWeatherProvider
from services.heatmap import heatmap_for
from services.plan import plan_weather

from .serializers import (
    AnalyzeRequestSerializer,
    AnalyzeResponseSerializer,
    HeatmapRequestSerializer,
    HeatmapResponseSerializer,
    PlanRequestSerializer,
    PlanResponseSerializer,
)
from .throttles import ClientRateThrottle


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


def weather_for(serializer):
    """The weather the browser supplied, or the server's own Open-Meteo fetch when it sent none."""
    supplied = serializer.validated_data.get("weather")
    return container.weather_provider() if supplied is None else SuppliedWeatherProvider(supplied)


@api_view(["POST"])
@throttle_classes([ClientRateThrottle])
def plan(request):
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = plan_weather(serializer.save(), request.request_id, container.routing_provider())
    return Response(PlanResponseSerializer(result).data)


@api_view(["POST"])
@throttle_classes([ClientRateThrottle])
def analyze(request):
    serializer = AnalyzeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = analyze_trip(
        serializer.save(), request.request_id, container.routing_provider(), weather_for(serializer)
    )
    return Response(AnalyzeResponseSerializer(result).data)


@api_view(["POST"])
@throttle_classes([ClientRateThrottle])
def heatmap(request):
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = heatmap_for(serializer.save(), request.request_id, weather_for(serializer))
    return Response(HeatmapResponseSerializer(result).data)
