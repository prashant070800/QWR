"""Provider factory — resolves the configured AI_PROVIDER to a concrete LLMProvider.

This is the ONLY place that knows about all available provider implementations.
To add a new provider:
  1. Create a new file in ai_agent/providers/
  2. Add an entry to the REGISTRY dict below.

That's it.  The rest of the codebase only interacts with the LLMProvider interface.
"""

from __future__ import annotations

import logging

from ai_agent.config import AgentSettings
from .base import LLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider(settings: AgentSettings) -> LLMProvider:
    """Return a ready-to-use LLMProvider instance based on *settings*.

    The provider type comes from ``settings.ai_provider`` (i.e. the
    ``AI_PROVIDER`` environment variable).

    Raises
    ------
    ValueError
        If the provider name is not recognised.
    ImportError
        If the required third-party SDK is not installed.
    """
    provider_name = settings.ai_provider.lower()

    logger.info(
        "Initialising LLM provider=%s model=%s",
        provider_name,
        settings.ai_model,
    )

    if provider_name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.ai_model,
        )

    if provider_name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.ai_model,
        )

    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.ai_model,
        )

    raise ValueError(
        f"Unknown AI_PROVIDER={provider_name!r}. "
        f"Supported providers: 'gemini', 'openai', 'anthropic'."
    )
