"""ASGI config with HTTP and WebSocket routing."""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from telephony.routing import websocket_urlpatterns as telephony_ws
from chatbot.routing import websocket_urlpatterns as chatbot_ws


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qwr_voicebot.settings")

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": URLRouter(telephony_ws + chatbot_ws),
    }
)

