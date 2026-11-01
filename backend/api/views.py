from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from services import container
from services.analyze import analyze_trip
from services.heatmap import heatmap_for

from .serializers import (
    AnalyzeRequestSerializer,
    AnalyzeResponseSerializer,
    HeatmapRequestSerializer,
    HeatmapResponseSerializer,
)
from .throttles import ClientRateThrottle


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@throttle_classes([ClientRateThrottle])
def analyze(request):
    serializer = AnalyzeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = analyze_trip(
        serializer.save(), request.request_id, container.routing_provider(), container.weather_provider()
    )
    return Response(AnalyzeResponseSerializer(result).data)


@api_view(["POST"])
@throttle_classes([ClientRateThrottle])
def heatmap(request):
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = heatmap_for(serializer.save(), request.request_id, container.weather_provider())
    return Response(HeatmapResponseSerializer(result).data)
