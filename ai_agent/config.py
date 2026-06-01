"""Centralised configuration for the QWR AI Agent.

All settings are read from environment variables (or a .env file via
python-decouple).  No secret values are hard-coded here.

Usage
-----
    from ai_agent.config import settings

    print(settings.ai_provider)      # "gemini"
    print(settings.gemini_api_key)   # "AIza..."
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    """Return environment variable *key* or *default*.

    python-decouple is optional; fall back to plain os.environ so the module
    works even if decouple is not installed.
    """
    try:
        from decouple import config  # type: ignore[import-untyped]
        return config(key, default=default)
    except ImportError:
        return os.environ.get(key, default)


@dataclass(frozen=True)
class AgentSettings:
    """All runtime settings for the AI agent layer."""

    # ------------------------------------------------------------------ #
    # LLM provider selection                                               #
    # ------------------------------------------------------------------ #
    # Supported values: "gemini" | "openai" | "anthropic"
    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "gemini"))

    # The exact model string forwarded to the chosen provider's API
    # Gemini default:   gemini-3.5-flash
    # OpenAI default:   gpt-4o-mini
    # Anthropic default: claude-3-5-haiku-20241022
    ai_model: str = field(
        default_factory=lambda: _env(
            "AI_MODEL",
            _default_model(_env("AI_PROVIDER", "gemini")),
        )
    )

    # Max tokens / output length hint
    ai_max_tokens: int = field(
        default_factory=lambda: int(_env("AI_MAX_TOKENS", "512"))
    )

    # ------------------------------------------------------------------ #
    # API keys — read from env, never committed                           #
    # ------------------------------------------------------------------ #
    gemini_api_key: str = field(
        default_factory=lambda: _env("GEMINI_API_KEY", "")
    )
    openai_api_key: str = field(
        default_factory=lambda: _env("OPENAI_API_KEY", "")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: _env("ANTHROPIC_API_KEY", "")
    )

    # ------------------------------------------------------------------ #
    # Supabase storage                                                   #
    # ------------------------------------------------------------------ #
    supabase_url: str = field(
        default_factory=lambda: _env("SUPABASE_URL", "")
    )
    supabase_key: str = field(
        default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY", "")
    )

    # ------------------------------------------------------------------ #
    # Google Cloud (STT + TTS)                                            #
    # ------------------------------------------------------------------ #
    google_credentials_path: str = field(
        default_factory=lambda: _env("GOOGLE_APPLICATION_CREDENTIALS", "")
    )

    # ------------------------------------------------------------------ #
    # QWR website scraper                                                 #
    # ------------------------------------------------------------------ #
    qwr_website_url: str = field(
        default_factory=lambda: _env("QWR_WEBSITE_URL", "https://questionwhatsreal.com/")
    )
    # How long (seconds) to cache scraped page content in memory
    qwr_cache_ttl_seconds: int = field(
        default_factory=lambda: int(_env("QWR_CACHE_TTL_SECONDS", "3600"))
    )

    # ------------------------------------------------------------------ #
    # Supabase persistence settings                                      #
    # ------------------------------------------------------------------ #
    supabase_url: str = field(
        default_factory=lambda: _env("SUPABASE_URL", "")
    )
    supabase_key: str = field(
        default_factory=lambda: _env("SUPABASE_KEY", "")
    )

    # ------------------------------------------------------------------ #
    # Exotel                                                              #
    # ------------------------------------------------------------------ #
    exotel_account_sid: str = field(
        default_factory=lambda: _env("EXOTEL_ACCOUNT_SID", "")
    )
    exotel_auth_token: str = field(
        default_factory=lambda: _env("EXOTEL_AUTH_TOKEN", "")
    )

    # ------------------------------------------------------------------ #
    # STT settings                                                        #
    # ------------------------------------------------------------------ #
    # "google" | "deepgram" | "stub" (stub returns a canned response for testing)
    stt_provider: str = field(
        default_factory=lambda: _env("STT_PROVIDER", "stub")
    )
    deepgram_api_key: str = field(
        default_factory=lambda: _env("DEEPGRAM_API_KEY", "")
    )
    # Silence threshold: how many consecutive silent PCM chunks before we
    # consider the user has finished speaking and send audio to STT.
    stt_silence_chunks: int = field(
        default_factory=lambda: int(_env("STT_SILENCE_CHUNKS", "10"))
    )

    # ------------------------------------------------------------------ #
    # TTS settings                                                        #
    # ------------------------------------------------------------------ #
    # "gtts" | "google" | "stub" (stub returns silent audio for tests)
    tts_provider: str = field(
        default_factory=lambda: _env("TTS_PROVIDER", "gtts")
    )
    # BCP-47 language code for TTS synthesis
    tts_language_code: str = field(
        default_factory=lambda: _env("TTS_LANGUAGE_CODE", "en-IN")
    )
    tts_voice_name: str = field(
        default_factory=lambda: _env("TTS_VOICE_NAME", "en-IN-Wavenet-A")
    )
    tts_speaking_rate: float = field(
        default_factory=lambda: float(_env("TTS_SPEAKING_RATE", "1.15"))
    )

    # ── AI Agent dynamic settings ──
    ai_welcome_message: str = field(
        default_factory=lambda: _env("AI_WELCOME_MESSAGE", "Welcome to QWR, how can I help you?")
    )
    ai_agent_name: str = field(
        default_factory=lambda: _env("AI_AGENT_NAME", "QWR Assistant")
    )
    ai_system_prompt: str = field(
        default_factory=lambda: _env("AI_SYSTEM_PROMPT", "")
    )

    def validate(self) -> None:
        """Raise ValueError for obviously wrong configurations."""
        provider = self.ai_provider.lower()
        key_map = {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }
        if provider not in key_map:
            raise ValueError(
                f"Unknown AI_PROVIDER={provider!r}. "
                f"Supported: {list(key_map)}"
            )
        if not key_map[provider]:
            raise ValueError(
                f"AI_PROVIDER={provider!r} requires {provider.upper()}_API_KEY to be set."
            )


def _default_model(provider: str) -> str:
    """Return a sensible default model for each supported provider."""
    defaults = {
        "gemini": "gemini-3.5-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-20241022",
    }
    return defaults.get(provider.lower(), "gemini-3.5-flash")


# Module-level singleton — import this everywhere
settings = AgentSettings()
