"""Lightweight chat agent — no scraper, no vector DB, no crawling.

Designed for minimum latency text chat. Uses the same LLM provider
infrastructure as the voice bot but strips all context-fetching overhead.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ai_agent.config import settings
from ai_agent.providers.base import LLMProvider, Message
from ai_agent.providers.factory import get_llm_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default system prompt — generic AI assistant
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """\
You are Nova, a smart, friendly, and helpful AI assistant.

Your personality:
- Warm and approachable, but concise and to the point.
- You explain complex topics in simple terms.
- You're honest when you don't know something.
- You use a conversational, natural tone — not robotic.

Guidelines:
- Keep responses SHORT and focused (2–4 sentences unless asked for detail).
- Use markdown formatting when it helps readability (code blocks, bold, lists).
- If the user asks something ambiguous, ask ONE clarifying question.
- Never make up facts, URLs, or data you're not sure about.
- Be helpful first, polite second — don't pad responses with filler.
"""


@dataclass
class ConversationTurn:
    """A single exchange in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.monotonic)
    latency_ms: float | None = None


class ChatAgent:
    """Stateful chat agent with conversation memory.

    Create one per chat session. Optimised for lowest latency:
    - No website scraping
    - No vector DB lookups
    - No embedding calls
    - Direct LLM call with minimal history
    """

    def __init__(
        self,
        session_id: str = "default",
        llm: LLMProvider | None = None,
        system_prompt: str | None = None,
        agent_name: str | None = None,
        max_history_turns: int = 10,
    ) -> None:
        self.session_id = session_id
        self._llm: LLMProvider = llm or get_llm_provider(settings)
        self._history: list[ConversationTurn] = []
        self._max_history = max_history_turns

        # Build system prompt
        self.agent_name = agent_name or "Nova"
        base_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        if agent_name and agent_name != "Nova":
            base_prompt = f"Your name is {agent_name}.\n{base_prompt}"

        self.system_prompt = base_prompt

        logger.info(
            "ChatAgent initialised session=%s provider=%s model=%s",
            self.session_id,
            self._llm.provider_name,
            self._llm.model_name,
        )

    async def chat(self, user_text: str) -> str:
        """Process user message and return the assistant's reply.

        Optimised path: system prompt + trimmed history + user message → LLM.
        """
        if not user_text.strip():
            return ""

        t0 = time.monotonic()

        # Build messages
        messages: list[Message] = [
            Message(role="system", content=self.system_prompt),
        ]

        # Add recent history (capped for speed)
        for turn in self._history[-(self._max_history * 2):]:
            messages.append(Message(role=turn.role, content=turn.content))

        # Add current user message
        messages.append(Message(role="user", content=user_text))

        # Call LLM
        reply = await self._llm.chat(messages, max_tokens=settings.ai_max_tokens)

        latency_ms = (time.monotonic() - t0) * 1000

        # Record turns
        self._history.append(ConversationTurn(role="user", content=user_text))
        self._history.append(
            ConversationTurn(role="assistant", content=reply, latency_ms=latency_ms)
        )

        logger.info(
            "ChatAgent reply session=%s latency_ms=%.0f chars=%d",
            self.session_id,
            latency_ms,
            len(reply),
        )

        return reply

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self._history.clear()

    def get_history(self) -> list[dict]:
        """Return conversation history as serializable dicts."""
        return [
            {
                "role": turn.role,
                "content": turn.content,
                "latency_ms": turn.latency_ms,
            }
            for turn in self._history
        ]
