"""WebSocket URL routing for the telephony app.

The consumer is selected at import time based on the VOICE_ENGINE setting:
    - "gemini_live" → GeminiLiveConsumer (audio-to-audio, sub-second latency)
    - "pipeline"    → ExotelVoicebotConsumer (traditional STT → LLM → TTS)

Set VOICE_ENGINE in your .env file. Default is "gemini_live".
"""

from django.urls import path

from ai_agent.config import settings

if settings.voice_engine.lower() == "gemini_live":
    from .consumers_live import GeminiLiveConsumer as _Consumer
else:
    from .consumers import ExotelVoicebotConsumer as _Consumer

websocket_urlpatterns = [
    path("ws/exotel/voicebot/", _Consumer.as_asgi()),
]
