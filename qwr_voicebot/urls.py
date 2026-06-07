from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from django.views.generic import RedirectView


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("dashboard/", include("telephony.urls")),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
]
