"""Anthropic Claude LLM provider.

Uses the official ``anthropic`` SDK.
Install: pip install anthropic
"""

from __future__ import annotations

import logging

from .base import LLMProvider, Message, TokenUsage

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """LLM provider backed by Anthropic Claude."""

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022") -> None:
        self._api_key = api_key
        self._model = model
        self._last_usage = TokenUsage()

    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 512,
    ) -> str:
        try:
            import anthropic  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "anthropic is not installed. Run: pip install anthropic"
            ) from exc

        client = anthropic.AsyncAnthropic(api_key=self._api_key)

        # Anthropic uses a separate 'system' kwarg; filter it out of messages
        system_parts: list[str] = []
        anthropic_messages: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                anthropic_messages.append(msg.to_dict())

        system_text = "\n\n".join(system_parts)

        logger.debug(
            "Anthropic chat model=%s turns=%d max_tokens=%d",
            self._model,
            len(anthropic_messages),
            max_tokens,
        )

        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_text:
            kwargs["system"] = system_text

        response = await client.messages.create(**kwargs)
        reply = (response.content[0].text if response.content else "").strip()
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        self._last_usage = TokenUsage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

        logger.info(
            "Anthropic reply model=%s length=%d tokens=%d preview=%r",
            self._model,
            len(reply),
            self._last_usage.total_tokens,
            reply[:80],
        )
        return reply

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model
