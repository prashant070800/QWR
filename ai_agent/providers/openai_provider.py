"""OpenAI LLM provider.

Uses the official ``openai`` SDK (>=1.0).
Install: pip install openai
"""

from __future__ import annotations

import logging

from .base import LLMProvider, Message

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI (ChatCompletion API)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 512,
    ) -> str:
        try:
            from openai import AsyncOpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "openai is not installed. Run: pip install openai"
            ) from exc

        client = AsyncOpenAI(api_key=self._api_key)

        openai_messages = [msg.to_dict() for msg in messages]

        logger.debug(
            "OpenAI chat model=%s turns=%d max_tokens=%d",
            self._model,
            len(openai_messages),
            max_tokens,
        )

        response = await client.chat.completions.create(
            model=self._model,
            messages=openai_messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=0.7,
        )

        reply = (response.choices[0].message.content or "").strip()

        logger.info(
            "OpenAI reply model=%s length=%d preview=%r",
            self._model,
            len(reply),
            reply[:80],
        )
        return reply

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model
