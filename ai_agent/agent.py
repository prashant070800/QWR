"""QWR AI Agent — orchestrates LLM + QWR website context.

The agent maintains per-call conversation history and automatically fetches
relevant QWR website content before generating a reply.

Usage (in a WebSocket consumer)
---------------------------------
    agent = QWRAgent(call_sid="CA123", stream_sid="MZ456")
    reply = await agent.chat("What VR headsets does QWR make?")
    # → "QWR makes the VRone series of standalone VR headsets..."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ai_agent.config import settings
from ai_agent.providers.base import LLMProvider, Message
from ai_agent.providers.factory import get_llm_provider
from ai_agent.tools.qwr_scraper import QWRScraper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# QWR System Prompt
# ---------------------------------------------------------------------------

QWR_SYSTEM_PROMPT = """\
You are a friendly, professional AI voice assistant for QWR (Question What's Real), \
India's leading manufacturer of VR headsets, AR glasses, and AI wearables, \
headquartered in Pune.

Your job is to:
1. Answer questions about QWR's products, services, industries, and company.
2. Help callers understand QWR's ODM/OEM services, HUMBL AI platform, and defence solutions.
3. Collect the caller's name, company, role, city, and reason for calling (intake).
4. Offer to connect callers with the right QWR team for follow-up.

Key facts about QWR:
- Founded 2017 in Pune by Suraj Aiar.
- India's largest VR education provider: 35,000+ learners across 500+ schools.
- 50,000+ devices shipped to 17+ countries.
- 110+ reference architectures.
- Products: VRone Edu, VRone Pro, VRone 4K, VRone PC, HUMBL AI Glasses, HUMBL AR.
- Make in India Class 1 certified, BIS certified, WPC approved.
- Strategic EMS partners: Kaynes Technology, Syrma SGS.
- HUMBL: India's first voice-native multimodal AI glasses, DPDP Act 2023 compliant.
- Defence: DAP 2020 Buy Indian (IDDM) eligible, MIL-STD-810H compliant, no foreign backdoors.

Important guidelines:
- Keep answers SHORT and conversational (2–3 sentences max) since this is a phone call.
- Speak naturally, as if talking on the phone.
- If you don't know something, say you'll connect them with the QWR team.
- Do NOT make up specific prices, dates, or technical specs not in the context provided.
- After answering, gently ask if the caller has more questions or would like a callback.
"""


@dataclass
class ConversationTurn:
    """A single exchange in the call conversation."""

    speaker: str       # "user" or "assistant"
    text: str
    timestamp: float = field(default_factory=time.monotonic)
    latency_ms: float | None = None  # For assistant turns: LLM+TTS latency


class QWRAgent:
    """Per-call AI agent with conversation memory and QWR website context.

    Create one instance per active call.  Thread/task safety: this class is
    designed to be used from a single asyncio task (the WebSocket consumer).
    """

    def __init__(
        self,
        call_sid: str | None = None,
        stream_sid: str | None = None,
        llm: LLMProvider | None = None,
        scraper: QWRScraper | None = None,
    ) -> None:
        self.call_sid = call_sid or "unknown"
        self.stream_sid = stream_sid or "unknown"

        self._llm: LLMProvider = llm or get_llm_provider(settings)
        self._scraper: QWRScraper = scraper or QWRScraper(
            cache_ttl_seconds=settings.qwr_cache_ttl_seconds
        )

        self._history: list[ConversationTurn] = []
        self._log_prefix = f"call_sid={self.call_sid} stream_sid={self.stream_sid}"

        logger.info(
            "%s QWRAgent initialised provider=%s model=%s",
            self._log_prefix,
            self._llm.provider_name,
            self._llm.model_name,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(self, user_text: str) -> str:
        """Process a user utterance and return the agent's reply.

        Steps:
        1. Fetch relevant QWR website context for this query.
        2. Build message list (system prompt + history + context + user turn).
        3. Send to configured LLM.
        4. Record turn in history with latency.
        5. Return reply text.
        """
        t0 = time.monotonic()

        logger.info(
            "%s User utterance: %r",
            self._log_prefix,
            user_text,
        )

        # Step 1: fetch QWR context
        qwr_context = await self._scraper.get_context(user_text)

        logger.info(
            "%s QWR context fetched chars=%d",
            self._log_prefix,
            len(qwr_context),
        )

        # Step 2: build messages
        messages = self._build_messages(user_text, qwr_context)

        # Step 3: call LLM
        reply = await self._llm.chat(messages, max_tokens=settings.ai_max_tokens)

        latency_ms = (time.monotonic() - t0) * 1000

        logger.info(
            "%s AI reply provider=%s model=%s latency_ms=%.0f preview=%r",
            self._log_prefix,
            self._llm.provider_name,
            self._llm.model_name,
            latency_ms,
            reply[:100],
        )

        # Step 4: record turns
        self._history.append(ConversationTurn(speaker="user", text=user_text))
        self._history.append(
            ConversationTurn(speaker="assistant", text=reply, latency_ms=latency_ms)
        )

        return reply

    async def get_greeting(self) -> str:
        """Return the opening greeting message for a new call."""
        greeting = (
            "Hello! Welcome to QWR, India's leading XR hardware company. "
            "I'm your AI assistant. I can answer questions about our VR headsets, "
            "AR glasses, AI wearables, and enterprise solutions. "
            "How can I help you today?"
        )
        logger.info("%s Sending greeting to caller", self._log_prefix)
        self._history.append(ConversationTurn(speaker="assistant", text=greeting))
        return greeting

    def get_transcript(self) -> list[dict]:
        """Return the full call transcript as a list of dicts for logging/storage."""
        return [
            {
                "speaker": turn.speaker,
                "text": turn.text,
                "timestamp": turn.timestamp,
                "latency_ms": turn.latency_ms,
            }
            for turn in self._history
        ]

    def update_call_ids(self, call_sid: str, stream_sid: str) -> None:
        """Update call identifiers (available after Exotel 'start' event)."""
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        self._log_prefix = f"call_sid={self.call_sid} stream_sid={self.stream_sid}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(self, user_text: str, qwr_context: str) -> list[Message]:
        """Assemble the full message list to send to the LLM."""
        messages: list[Message] = []

        # System prompt
        system_content = QWR_SYSTEM_PROMPT
        if qwr_context:
            system_content += (
                "\n\n--- LIVE QWR WEBSITE CONTEXT ---\n"
                "Use the following live content from questionwhatsreal.com "
                "to answer accurately:\n\n"
                + qwr_context
            )

        messages.append(Message(role="system", content=system_content))

        # Prior conversation history (last 6 turns to keep context window small)
        for turn in self._history[-6:]:
            role = "user" if turn.speaker == "user" else "assistant"
            messages.append(Message(role=role, content=turn.text))

        # Current user message
        messages.append(Message(role="user", content=user_text))

        return messages
