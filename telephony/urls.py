from django.urls import path
from . import views

app_name = "telephony"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("call/<int:pk>/", views.CallDetailView.as_view(), name="call_detail"),
]
