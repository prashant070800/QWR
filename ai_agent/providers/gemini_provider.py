"""Google Gemini LLM provider.

Uses the official ``google-generativeai`` SDK.
Install: pip install google-generativeai
"""

from __future__ import annotations

import logging

from .base import LLMProvider, Message

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-exp") -> None:
        self._api_key = api_key
        self._model = model
        self._client = self._build_client()

    def _build_client(self):  # type: ignore[return]
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
            genai.configure(api_key=self._api_key)
            return genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 512,
    ) -> str:
        """Send conversation to Gemini and return the reply."""
        import asyncio

        # Separate system prompt from conversation turns
        system_parts: list[str] = []
        chat_turns: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                chat_turns.append({"role": "user", "parts": [msg.content]})
            elif msg.role == "assistant":
                chat_turns.append({"role": "model", "parts": [msg.content]})

        system_instruction = "\n\n".join(system_parts) if system_parts else None

        logger.debug(
            "Gemini chat model=%s turns=%d max_tokens=%d",
            self._model,
            len(chat_turns),
            max_tokens,
        )

        # google-generativeai is sync — run in executor to avoid blocking
        def _sync_call() -> str:
            import google.generativeai as genai  # type: ignore[import-untyped]

            model_kwargs: dict = {
                "generation_config": genai.types.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.7,
                ),
            }
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            model = genai.GenerativeModel(self._model, **model_kwargs)

            if chat_turns:
                # Use multi-turn chat
                history = chat_turns[:-1]  # all but last
                chat = model.start_chat(history=history)
                last_user_text = chat_turns[-1]["parts"][0] if chat_turns else ""
                response = chat.send_message(last_user_text)
            else:
                response = model.generate_content("")

            return response.text.strip()

        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _sync_call)

        logger.info(
            "Gemini reply model=%s length=%d preview=%r",
            self._model,
            len(reply),
            reply[:80],
        )
        return reply

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model
