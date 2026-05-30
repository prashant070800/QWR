"""WSGI config for conventional Django deployments."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qwr_voicebot.settings")

application = get_wsgi_application()
