"""Minimal settings for the QWR AI Voice Bot.

All secrets and tuneable values are read from environment variables.
Copy `.env.example` to `.env` and fill in your values.
"""

from __future__ import annotations

import os
import importlib.util
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    """Read an environment variable, with optional python-decouple support."""
    try:
        from decouple import config  # type: ignore[import-untyped]
        return config(key, default=default)
    except ImportError:
        return os.environ.get(key, default)


BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------------------------------------------------------
# Core Django settings
# -------------------------------------------------------------------------
SECRET_KEY = _env("DJANGO_SECRET_KEY", "dev-only-change-me-in-production")
DEBUG = _env("DJANGO_DEBUG", "true").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = _env("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "telephony",
    "chatbot",
]

if importlib.util.find_spec("jazzmin"):
    INSTALLED_APPS.insert(0, "jazzmin")

JAZZMIN_SETTINGS = {
    "site_title": "QWR Voice Bot Admin",
    "site_header": "QWR Voice Bot",
    "site_brand": "QWR Voice Bot",
    "welcome_sign": "QWR AI Voice Bot Admin",
    "copyright": "QWR Interactive Solutions",
    "show_sidebar": True,
    "navigation_expanded": True,
    "icons": {
        "telephony.Profile": "fas fa-user",
        "telephony.Call": "fas fa-phone",
        "telephony.TranscriptTurn": "fas fa-comments",
        "telephony.Summary": "fas fa-file-alt",
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "qwr_voicebot.urls"
ASGI_APPLICATION = "qwr_voicebot.asgi.application"
WSGI_APPLICATION = "qwr_voicebot.wsgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

# -------------------------------------------------------------------------
# Logging — structured with call/stream identifiers
# -------------------------------------------------------------------------
LOG_LEVEL = _env("LOG_LEVEL", "DEBUG")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname:8s} {name} — {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        # Telephony WebSocket consumer — show everything
        "telephony": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # AI agent modules
        "ai_agent": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # Channels / Daphne lifecycle
        "django.channels": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "daphne": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
