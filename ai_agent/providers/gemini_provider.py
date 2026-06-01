"""Google Gemini LLM provider.

Uses the official ``google-generativeai`` SDK.
Install: pip install google-generativeai
"""

from __future__ import annotations

import logging

from .base import LLMProvider, Message

logger = logging.getLogger(__name__)

GEMINI_FALLBACK_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.0-flash",
)


class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini."""

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash") -> None:
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
                parts = []
                if msg.content:
                    parts.append(msg.content)
                if msg.audio_data and msg.audio_mime:
                    parts.append({"mime_type": msg.audio_mime, "data": msg.audio_data})
                chat_turns.append({"role": "user", "parts": parts})
            elif msg.role == "assistant":
                chat_turns.append({"role": "model", "parts": [msg.content]})

        system_instruction = "\n\n".join(system_parts) if system_parts else None

        logger.debug(
            "Gemini chat model=%s turns=%d max_tokens=%d",
            self._model,
            len(chat_turns),
            max_tokens,
        )

        model_names = _candidate_model_names(self._model)

        # google-generativeai is sync — run in executor to avoid blocking
        def _sync_call() -> tuple[str, str]:
            import google.generativeai as genai  # type: ignore[import-untyped]

            model_kwargs: dict = {
                "generation_config": genai.types.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.7,
                ),
            }
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            last_error: Exception | None = None
            for model_name in model_names:
                try:
                    model = genai.GenerativeModel(model_name, **model_kwargs)

                    if chat_turns:
                        # Use multi-turn chat
                        history = chat_turns[:-1]  # all but last
                        chat = model.start_chat(history=history)
                        last_user_parts = chat_turns[-1]["parts"]
                        response = chat.send_message(last_user_parts)
                    else:
                        response = model.generate_content("")

                    return response.text.strip(), model_name
                except Exception as exc:
                    if not _is_unavailable_model_error(exc):
                        raise
                    last_error = exc
                    logger.warning(
                        "Gemini model unavailable model=%s error=%s",
                        model_name,
                        exc,
                    )

            if last_error is not None:
                raise last_error
            raise RuntimeError("No Gemini model candidates configured")

        loop = asyncio.get_event_loop()
        reply, model_name = await loop.run_in_executor(None, _sync_call)

        logger.info(
            "Gemini reply model=%s length=%d preview=%r",
            model_name,
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


def _candidate_model_names(primary_model: str) -> list[str]:
    names = [primary_model, *GEMINI_FALLBACK_MODELS]
    deduped: list[str] = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    return deduped


def _is_unavailable_model_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "is not found" in message
        or "not_found" in message
        or "not supported for generatecontent" in message
        or "quota" in message
        or "exhausted" in message
        or "429" in message
        or "resource_exhausted" in message
        or "limit" in message
    )
