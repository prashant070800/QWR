"""Google Gemini LLM provider.

Uses the official ``google-generativeai`` SDK.
Install: pip install google-generativeai
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

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
            api_key = self._api_key.strip("'\"")
            genai.configure(api_key=api_key, transport="rest")
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

                    text = ""
                    try:
                        text = response.text.strip()
                    except ValueError:
                        if response.candidates:
                            candidate = response.candidates[0]
                            if candidate.content and candidate.content.parts:
                                text = "".join(part.text for part in candidate.content.parts if part.text).strip()
                    if not text:
                        reason = "unknown"
                        if response.candidates:
                            reason = str(response.candidates[0].finish_reason)
                        raise ValueError(f"Gemini returned empty response or blocked. Finish reason: {reason}")
                    return text, model_name
                except Exception as exc:
                    if not _is_unavailable_model_error(exc) and not isinstance(exc, ValueError):
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

    async def chat_stream(
        self,
        messages: list[Message],
        max_tokens: int = 512,
    ) -> AsyncIterator[str]:
        """Send conversation to Gemini and yield chunks as they arrive."""
        import asyncio
        import threading

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
            "Gemini chat_stream model=%s turns=%d max_tokens=%d",
            self._model,
            len(chat_turns),
            max_tokens,
        )

        model_names = _candidate_model_names(self._model)
        queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _sync_stream_worker() -> None:
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
                        history = chat_turns[:-1]
                        chat = model.start_chat(history=history)
                        last_user_parts = chat_turns[-1]["parts"]
                        response = chat.send_message(last_user_parts, stream=True)
                    else:
                        response = model.generate_content("", stream=True)

                    for chunk in response:
                        chunk_text = ""
                        try:
                            chunk_text = chunk.text
                        except ValueError:
                            if chunk.candidates:
                                candidate = chunk.candidates[0]
                                if candidate.content and candidate.content.parts:
                                    chunk_text = "".join(part.text for part in candidate.content.parts if part.text)
                        if chunk_text:
                            loop.call_soon_threadsafe(queue.put_nowait, chunk_text)
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                    return
                except Exception as exc:
                    if not _is_unavailable_model_error(exc):
                        loop.call_soon_threadsafe(queue.put_nowait, exc)
                        return
                    last_error = exc
                    logger.warning(
                        "Gemini model unavailable in stream model=%s error=%s",
                        model_name,
                        exc,
                    )

            if last_error is not None:
                loop.call_soon_threadsafe(queue.put_nowait, last_error)
            else:
                loop.call_soon_threadsafe(
                    queue.put_nowait, RuntimeError("No Gemini model candidates configured")
                )

        thread = threading.Thread(target=_sync_stream_worker, daemon=True)
        thread.start()

        has_yielded = False
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                has_yielded = True
                yield item
        except Exception as exc:
            if not has_yielded:
                logger.warning(
                    "Gemini streaming failed: %s. Falling back to non-streaming chat.",
                    exc,
                )
                try:
                    reply = await self.chat(messages, max_tokens=max_tokens)
                    yield reply
                except Exception as chat_exc:
                    logger.error("Gemini non-streaming chat fallback also failed: %s", chat_exc)
                    raise chat_exc
            else:
                raise exc

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
