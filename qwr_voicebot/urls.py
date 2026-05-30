"""HTTP URLs for health checks and later dashboard views."""

from django.http import JsonResponse
from django.urls import path


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
]
