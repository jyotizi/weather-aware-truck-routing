from django.urls import path

from planner.views import GeocodeView, HealthView, PlanView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("geocode/", GeocodeView.as_view(), name="geocode"),
    path("plan/", PlanView.as_view(), name="plan"),
]
