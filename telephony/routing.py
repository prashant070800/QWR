from django.urls import path

from .consumers import ExotelVoicebotConsumer


websocket_urlpatterns = [
    path("ws/exotel/voicebot/", ExotelVoicebotConsumer.as_asgi()),
]
