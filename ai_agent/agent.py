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
- Speak naturally, as if talking on the phone with a real person.
- Use simple everyday words, contractions, and brief acknowledgements like "Sure" or "Got it" when they fit.
- Do not sound like a script, brochure, or long FAQ answer.
- Ask only one follow-up question at a time.
- Avoid bullet lists unless the caller explicitly asks for a list.
- If you don't know something, say you'll connect them with the QWR team.
- Do NOT make up specific prices, dates, or technical specs not in the context provided.
- After answering, gently ask if the caller has more questions or would like a callback.
"""


import io
import wave
import re

def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 8000) -> bytes:
    """Wrap raw mono 16-bit PCM bytes into a standard WAV header container."""
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return wav_buf.getvalue()

def parse_gemini_response(response_text: str) -> tuple[str, str]:
    """Parse Gemini's structured response to extract user transcript and agent reply.

    Expected format:
    User transcript: <what the user said>
    Agent reply: <what the agent responded>
    """
    user_tx = ""
    agent_reply = ""

    # Try regex match (case-insensitive, allowing asterisks or markup)
    match = re.search(
        r"User\s*transcript\s*:\s*(.*?)\n+Agent\s*reply\s*:\s*(.*)",
        response_text,
        re.DOTALL | re.IGNORECASE
    )
    if match:
        user_tx = match.group(1).strip()
        agent_reply = match.group(2).strip()
    else:
        # Fallback line-by-line parser
        lines = response_text.split("\n")
        user_lines = []
        agent_lines = []
        in_user = False
        in_agent = False
        for line in lines:
            lower_line = line.lower().strip()
            if "user transcript:" in lower_line:
                in_user = True
                in_agent = False
                part = line.split(":", 1)[1].strip()
                if part:
                    user_lines.append(part)
            elif "agent reply:" in lower_line:
                in_agent = True
                in_user = False
                part = line.split(":", 1)[1].strip()
                if part:
                    agent_lines.append(part)
            else:
                if in_user:
                    user_lines.append(line.strip())
                elif in_agent:
                    agent_lines.append(line.strip())

        user_tx = " ".join(user_lines).strip()
        agent_reply = " ".join(agent_lines).strip()

    # Clean up markdown formatting characters like asterisks or quotes
    user_tx = re.sub(r"^['\"\*#\s\-]+|['\"\*#\s\-]+$", "", user_tx)
    agent_reply = re.sub(r"^['\"\*#\s\-]+|['\"\*#\s\-]+$", "", agent_reply)

    if not agent_reply:
        agent_reply = response_text
        user_tx = "Audio input"

    return user_tx, agent_reply


@dataclass
class ConversationTurn:
    """A single exchange in the call conversation."""

    speaker: str       # "user" or "assistant"
    text: str
    role: str = "" # Backwards compatibility or future use
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
        system_prompt: str | None = None,
        agent_name: str | None = None,
        welcome_message: str | None = None,
    ) -> None:
        self.call_sid = call_sid or "unknown"
        self.stream_sid = stream_sid or "unknown"

        self._llm: LLMProvider = llm or get_llm_provider(settings)
        
        # Use shared scraper to avoid network latency on cache miss per call
        from ai_agent.tools.qwr_scraper import shared_scraper
        self._scraper: QWRScraper = scraper or shared_scraper

        self._history: list[ConversationTurn] = []
        self._log_prefix = f"call_sid={self.call_sid} stream_sid={self.stream_sid}"

        self.agent_name = agent_name or settings.ai_agent_name
        self.welcome_message = welcome_message or settings.ai_welcome_message

        # Determine the base system prompt
        base_prompt = system_prompt or settings.ai_system_prompt or QWR_SYSTEM_PROMPT
        
        # If agent name is set, inject it into the prompt instruction
        if self.agent_name:
            base_prompt = f"Your name is {self.agent_name}. Speak as {self.agent_name}.\n{base_prompt}"
        
        self.system_prompt = base_prompt + (
            "\n\nIMPORTANT: For every turn of the conversation, you will receive "
            "either a text prompt or audio data representing the user speaking. "
            "You MUST first transcribe exactly what the user said (if it is audio), "
            "or repeat their input (if it is text). Then, you MUST write your "
            "conversational reply. You MUST format your entire response exactly "
            "like this:\n"
            "User transcript: <what the user said>\n"
            "Agent reply: <your response to the user>\n"
            "Do not include any other markdown or text outside this format."
        )

        logger.info(
            "%s QWRAgent initialised provider=%s model=%s agent_name=%s welcome_msg=%s",
            self._log_prefix,
            self._llm.provider_name,
            self._llm.model_name,
            self.agent_name,
            self.welcome_message,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_text: str | None = None,
        audio_bytes: bytes | None = None,
        sample_rate: int = 8000,
    ) -> tuple[str, str]:
        """Process a user utterance and return the agent's reply.

        Steps:
        1. Fetch relevant QWR website context for this query.
        2. Build message list (system prompt + history + context + user turn).
        3. Send to configured LLM.
        4. Record turn in history with latency.
        5. Return (user_transcript, agent_reply) tuple.
        """
        t0 = time.monotonic()

        # Step 1: fetch QWR context
        qwr_context = await self._scraper.get_context(user_text or "")

        # Step 2: convert audio if present
        wav_bytes = None
        if audio_bytes:
            wav_bytes = pcm_to_wav(audio_bytes, sample_rate)

        # Step 3: build messages
        audio_mime = "audio/wav" if wav_bytes else None
        messages = self._build_messages(
            user_text,
            qwr_context,
            audio_data=wav_bytes,
            audio_mime=audio_mime,
        )

        # Step 4: call LLM
        raw_reply = await self._llm.chat(messages, max_tokens=settings.ai_max_tokens)

        # Step 5: parse structured response
        user_transcript, agent_reply = parse_gemini_response(raw_reply)

        # If user_text was passed directly (like DTMF), override user_transcript
        if user_text and not audio_bytes:
            user_transcript = user_text

        latency_ms = (time.monotonic() - t0) * 1000

        # Step 6: record turns
        self._history.append(ConversationTurn(speaker="user", text=user_transcript))
        self._history.append(
            ConversationTurn(speaker="assistant", text=agent_reply, latency_ms=latency_ms)
        )

        return user_transcript, agent_reply

    async def get_greeting(self) -> str:
        """Generate the opening greeting for a new call.
        
        If welcome_message is configured, return it immediately to avoid LLM call latency.
        """
        if self.welcome_message:
            logger.info("%s Using pre-configured welcome message greeting: %r", self._log_prefix, self.welcome_message)
            self._history.append(
                ConversationTurn(speaker="assistant", text=self.welcome_message, latency_ms=0.0)
            )
            return self.welcome_message

        # LLM fallback
        t0 = time.monotonic()
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(
                role="user",
                content=(
                    "The phone call has just connected. Start the conversation "
                    "like a helpful QWR representative. Keep it under 18 words "
                    "and ask how you can help."
                ),
            ),
        ]
        greeting = await self._llm.chat(messages, max_tokens=64)
        user_tx, agent_reply = parse_gemini_response(greeting)
        latency_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "%s AI greeting provider=%s model=%s latency_ms=%.0f preview=%r",
            self._log_prefix,
            self._llm.provider_name,
            self._llm.model_name,
            latency_ms,
            agent_reply[:100],
        )
        self._history.append(
            ConversationTurn(speaker="assistant", text=agent_reply, latency_ms=latency_ms)
        )
        return agent_reply

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

    def _build_messages(
        self,
        user_text: str | None,
        qwr_context: str,
        audio_data: bytes | None = None,
        audio_mime: str | None = None,
    ) -> list[Message]:
        """Assemble the full message list to send to the LLM."""
        messages: list[Message] = []

        # System prompt
        system_content = self.system_prompt
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
        content = user_text or ""
        messages.append(
            Message(
                role="user",
                content=content,
                audio_data=audio_data,
                audio_mime=audio_mime,
            )
        )

        return messages
