
import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from planner.services.errors import PlanError
from planner.services.plan import (
    parse_departure,
    parse_load,
    parse_place,
    parse_sample_miles,
    plan_trip,
)
from planner.services.providers import geocode_search
from planner.weather import WeatherServiceError

logger = logging.getLogger("planner")


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class GeocodeView(APIView):
    def get(self, request):
        try:
            results = geocode_search(request.query_params.get("q") or "")
        except PlanError as exc:
            return Response(
                {"detail": exc.message},
                status=exc.status,
            )

        return Response({"results": results})


class PlanView(APIView):
    def post(self, request):
        try:
            payload = plan_trip(
                parse_place(request.data.get("origin"), "origin"),
                parse_place(
                    request.data.get("destination"),
                    "destination",
                ),
                parse_departure(request.data.get("departure")),
                parse_load(request.data.get("load_weight_lb")),
                parse_sample_miles(request.data.get("sample_miles")),
            )

        except PlanError as exc:
            return Response(
                {"detail": exc.message},
                status=exc.status,
            )

        except WeatherServiceError as exc:
            logger.warning("Weather service unavailable: %s", exc)
            return Response(
                {
                    "detail": str(exc),
                    "weather_available": False,
                },
                status=503,
            )

        except Exception:
            logger.exception("plan failed")
            return Response(
                {"detail": "Could not plan that trip. Try again."},
                status=502,
            )

        return Response(payload)
