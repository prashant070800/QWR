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
from typing import AsyncIterator, Any

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
    """Wrap raw mono 16-bit PCM bytes into a standard WAV header container, stripping silence."""
    import struct
    num_samples = len(pcm_bytes) // 2
    if num_samples > 0:
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
            # Threshold 500 (standard threshold for 16-bit VAD)
            threshold = 500
            padding = int(sample_rate * 0.1)  # 100ms padding
            
            # Find first sample above threshold
            start_idx = 0
            for i, s in enumerate(samples):
                if abs(s) > threshold:
                    start_idx = max(0, i - padding)
                    break
            else:
                start_idx = 0

            # Find last sample above threshold
            end_idx = num_samples
            for i in range(num_samples - 1, -1, -1):
                if abs(samples[i]) > threshold:
                    end_idx = min(num_samples, i + padding)
                    break

            if start_idx < end_idx:
                pcm_bytes = pcm_bytes[start_idx * 2 : end_idx * 2]
        except Exception as exc:
            logger.warning("Failed to strip silence from PCM bytes: %s", exc)

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

    def __init__(self,
        call_sid: str | None = None,
        stream_sid: str | None = None,
        call_id: str | None = None,
        llm: LLMProvider | None = None,
        scraper: QWRScraper | None = None,
        system_prompt: str | None = None,
        agent_name: str | None = None,
        welcome_message: str | None = None,
        business_url: str | None = None,
    ) -> None:
        self.call_id = call_id or "unknown"
        self.call_sid = call_sid or "unknown"
        self.stream_sid = stream_sid or "unknown"

        self._llm: LLMProvider = llm or get_llm_provider(settings)
        
        # Use shared scraper to avoid network latency on cache miss per call
        from ai_agent.tools.qwr_scraper import shared_scraper, warm_up_cache
        self._scraper: QWRScraper = scraper or shared_scraper
        warm_up_cache()

        self.business_url = business_url or settings.qwr_website_url
        from urllib.parse import urlparse
        self.domain = urlparse(self.business_url).netloc.lower()

        # Trigger background crawl and indexing if not already indexed
        from ai_agent.tools.crawler import trigger_crawl
        trigger_crawl(self.business_url)

        self._history: list[ConversationTurn] = []
        self._log_prefix = f"call_id={self.call_id} call_sid={self.call_sid} stream_sid={self.stream_sid}"

        self.agent_name = agent_name or settings.ai_agent_name
        self.welcome_message = welcome_message

        # Determine the base system prompt
        base_prompt = system_prompt or settings.ai_system_prompt or QWR_SYSTEM_PROMPT
        
        # If agent name is set, inject it into the prompt instruction
        if self.agent_name:
            base_prompt = f"Your name is {self.agent_name}. Speak as {self.agent_name}.\n{base_prompt}"
        
        self.system_prompt = base_prompt + (
            "\n\nIMPORTANT: Keep your responses extremely short, direct, and conversational "
            "(maximum 10-15 words or 1-2 sentences). Do not include any introductory preambles or fluff. "
            "If the user asks for details, specs, contact info, or facts not present in your context, reply with "
            "exactly: [SEARCH: <query>]"
        )
        self.general_context = None

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

        This synchronous wrapper uses chat_stream under the hood.
        """
        t0 = time.monotonic()

        # Step 1: transcribe audio if present using configured STT
        if audio_bytes and not user_text:
            from ai_agent.stt import transcribe_audio
            user_text = await transcribe_audio(
                audio_bytes,
                sample_rate=sample_rate,
                call_sid=self.call_sid,
                stream_sid=self.stream_sid,
            )

        user_transcript = user_text or ""

        # Return empty reply early if user transcript is silence/empty to avoid repeating greetings
        if user_transcript.strip().lower() in ("", "[silence]", "silence"):
            return user_transcript, ""

        # Step 2: Fetch general context once
        if self.general_context is None:
            self.general_context = await self._get_general_context()

        # Step 3: Stream tokens into a complete string
        chunks = []
        async for chunk in self.chat_stream(user_text=user_transcript):
            chunks.append(chunk)
        
        raw_reply = "".join(chunks)

        # Step 4: Handle search intercept inside the sync wrapper if triggered
        if "[SEARCH:" in raw_reply:
            match = re.search(r"\[SEARCH:\s*(.*?)\]", raw_reply)
            if match:
                query = match.group(1).strip()
                search_res = await self._run_search(query)
                chunks = []
                async for chunk in self.chat_stream(user_text=user_transcript, search_context=search_res):
                    chunks.append(chunk)
                raw_reply = "".join(chunks)

        agent_reply = raw_reply.strip()
        latency_ms = (time.monotonic() - t0) * 1000

        # Step 5: record turns
        self.record_turn(user_transcript, agent_reply, latency_ms)

        return user_transcript, agent_reply

    async def chat_stream(
        self,
        user_text: str | None = None,
        search_context: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream reply chunks for user input, appending general and search context.

        Yields:
            str: Chunks of the agent's reply as they arrive from the LLM.
        """
        # Lazy load general context on first turn
        if self.general_context is None:
            self.general_context = await self._get_general_context()

        # Build messages using both cached general context and any dynamic search context
        messages = self._build_messages(
            user_text=user_text,
            general_context=self.general_context,
            search_context=search_context,
        )

        reply_stream = self._llm.chat_stream(messages, max_tokens=settings.ai_max_tokens)
        async for chunk in reply_stream:
            yield chunk

    async def _get_general_context(self) -> str:
        """Fetch general business context (homepage contents) once to embed in system prompt."""
        try:
            from ai_agent.tools.vector_db import SQLiteVectorDB
            db = SQLiteVectorDB()
            # Fast check if business status is completed
            status = db.get_business_status(self.domain)
            if status == "completed":
                chunks = db.get_first_chunks(self.domain, count=4)
                if chunks:
                    logger.info("%s Loaded general business context from SQLite Vector DB", self._log_prefix)
                    return "\n\n".join(chunks)

            # Fallback to loading home page from scraper cache/live
            logger.info("%s Vector DB not completed. Loading general context from scraper.", self._log_prefix)
            return await self._scraper.get_context("overview home contact info")
        except Exception as exc:
            logger.error("%s Failed to fetch general context: %s", self._log_prefix, exc)
            return ""

    async def _run_search(self, query: str) -> str:
        """Query vector database for dynamic search context."""
        import asyncio
        from ai_agent.tools.vector_db import SQLiteVectorDB
        import google.generativeai as genai

        logger.info("%s Intercepted SEARCH trigger. Searching vector DB for: %r", self._log_prefix, query)
        db = SQLiteVectorDB()
        search_query = query.strip()
        if not search_query:
            return ""

        try:
            loop = asyncio.get_running_loop()
            def _embed():
                return genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=search_query,
                    task_type="retrieval_query"
                )
            
            resp = await loop.run_in_executor(None, _embed)
            query_emb = resp.get("embedding", [])
            
            if not query_emb:
                logger.warning("Empty embedding returned for query=%r during SEARCH fallback", search_query)
                fallback_chunks = db.get_first_chunks(self.domain, count=3)
                return "\n\n".join(fallback_chunks)

            matches = db.search(self.domain, query_emb, top_k=3)
            if not matches:
                logger.warning("No vector matches found for query=%r during SEARCH fallback", search_query)
                fallback_chunks = db.get_first_chunks(self.domain, count=3)
                return "\n\n".join(fallback_chunks)

            return "\n\n".join([f"Source: {m['url']}\nContent: {m['text']}" for m in matches])
        except Exception as exc:
            logger.error("%s Search failed for query=%r: %s", self._log_prefix, search_query, exc)
            return await self._scraper.get_context(search_query)

    def record_turn(self, user_text: str, agent_reply: str, latency_ms: float) -> None:
        """Record completed conversation turns in history."""
        self._history.append(ConversationTurn(speaker="user", text=user_text))
        self._history.append(
            ConversationTurn(speaker="assistant", text=agent_reply, latency_ms=latency_ms)
        )

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

    def update_call_ids(self, call_sid: str, stream_sid: str, call_id: str | None = None) -> None:
        """Update call identifiers (available after Exotel 'start' event)."""
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        if call_id:
            self.call_id = call_id
        self._log_prefix = f"call_id={self.call_id} call_sid={self.call_sid} stream_sid={self.stream_sid}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        user_text: str | None,
        qwr_context: str | None = None,
        general_context: str | None = None,
        search_context: str | None = None,
        audio_data: bytes | None = None,
        audio_mime: str | None = None,
    ) -> list[Message]:
        """Assemble the full message list to send to the LLM."""
        messages: list[Message] = []

        # System prompt
        system_content = self.system_prompt
        if qwr_context:
            system_content += (
                f"\n\n--- LIVE WEBSITE CONTEXT FOR {self.business_url} ---\n"
                "Use the following live content from the business website "
                "to answer accurately:\n\n"
                + qwr_context
            )
        if general_context:
            system_content += (
                f"\n\n--- GENERAL BUSINESS CONTEXT ---\n"
                + general_context
            )
        if search_context:
            system_content += (
                f"\n\n--- ADDITIONAL LIVE WEBSITE SEARCH CONTEXT ---\n"
                "Use this newly fetched information to answer the question:\n"
                + search_context
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

    async def _get_context_from_db(self, query: str) -> str:
        """Fetch matching context from Vector DB, falling back to scraper if not fully indexed."""
        import asyncio
        from ai_agent.tools.vector_db import SQLiteVectorDB
        import google.generativeai as genai

        db = SQLiteVectorDB()
        status = db.get_business_status(self.domain)

        # Fallback to scraper if indexing is not completed yet
        if status != "completed":
            logger.info("Vector DB indexing status for domain=%s is %s, falling back to real-time scraper", self.domain, status)
            return await self._scraper.get_context(query)

        search_query = query.strip()
        if not search_query:
            if self._history:
                # Use last 2 turns of text history to maintain context
                search_query = " ".join([t.text for t in self._history[-2:]])
            else:
                search_query = "overview home contact info"

        try:
            loop = asyncio.get_running_loop()
            def _embed():
                return genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=search_query,
                    task_type="retrieval_query"
                )
            
            resp = await loop.run_in_executor(None, _embed)
            query_emb = resp.get("embedding", [])
            
            if not query_emb:
                logger.warning("Empty embedding returned for query=%r, falling back to first chunks", search_query)
                fallback_chunks = db.get_first_chunks(self.domain, count=3)
                return "\n\n".join(fallback_chunks)

            matches = db.search(self.domain, query_emb, top_k=3)
            if not matches:
                logger.warning("No vector matches found for query=%r, falling back to first chunks", search_query)
                fallback_chunks = db.get_first_chunks(self.domain, count=3)
                return "\n\n".join(fallback_chunks)

            return "\n\n".join([f"Source: {m['url']}\nContent: {m['text']}" for m in matches])

        except Exception as exc:
            logger.error("Vector search failed for domain=%s query=%r: %s", self.domain, search_query, exc)
            return await self._scraper.get_context(query)

    async def generate_summary(self, turns: list[dict[str, Any]]) -> str:
        """Generate a concise summary of the conversation turns using the configured LLM."""
        if not turns:
            return "No conversation turns recorded."

        formatted_turns = []
        for turn in sorted(turns, key=lambda t: t.get("seq_number", 0)):
            speaker = str(turn.get("speaker", "unknown")).upper()
            text = turn.get("text", "")
            formatted_turns.append(f"{speaker}: {text}")

        transcript_str = "\n".join(formatted_turns)

        prompt = (
            "Summarize the following phone conversation between a user and an AI assistant. "
            "Focus on the user's inquiry, the outcome, and any next steps.\n\n"
            f"Transcript:\n{transcript_str}\n\n"
            "Summary:"
        )

        from ai_agent.providers.gemini_provider import Message
        messages = [
            Message(role="system", content="You are a helpful assistant that summarizes telephone calls."),
            Message(role="user", content=prompt)
        ]

        try:
            summary = await self._llm.chat(messages, max_tokens=256)
            return summary.strip()
        except Exception as exc:
            logger.exception("%s Failed to generate summary via LLM: %s", self._log_prefix, exc)
            return f"Summary generation failed: {exc}"
