"""Exotel WebSocket consumer powered by Gemini Live API.

This consumer replaces the traditional STT → LLM → TTS pipeline with
Gemini's native audio-to-audio model for sub-second latency voice calls.

Audio flow:
    Exotel 8kHz PCM → resample 16kHz → Gemini Live WS → receive 24kHz PCM
    → resample 8kHz → chunk + base64 → Exotel media frames

Selected via VOICE_ENGINE=gemini_live in .env (default).

The old pipeline consumer lives in consumers.py and is selected with
VOICE_ENGINE=pipeline.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from ai_agent.config import settings
from ai_agent.gemini_live import GeminiLiveSession, LiveTranscript
from ai_agent.agent import QWR_SYSTEM_PROMPT
from ai_agent.storage import CallStorage

from .audio import (
    EXOTEL_CHANNELS,
    EXOTEL_SAMPLE_RATE_HZ,
    EXOTEL_SAMPLE_WIDTH_BYTES,
    b64_audio,
    chunk_pcm,
    chunk_duration_seconds,
)
from .phone_numbers import to_e164
from .silence_watchdog import SilenceWatchdog

logger = logging.getLogger(__name__)

SUPPORTED_EXOTEL_ENCODINGS = {"raw/slin", "slin", "linear16", "pcm", "base64", ""}
SUPPORTED_EXOTEL_SAMPLE_RATES = {8000, 16000, 24000}


# ---------------------------------------------------------------------------
# Call state
# ---------------------------------------------------------------------------

@dataclass
class LiveCallState:
    """Metadata and buffers for one active Gemini Live call."""

    # Exotel identifiers
    stream_sid: str | None = None
    call_sid: str | None = None
    account_sid: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    media_format: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None

    # State flags
    is_stopped: bool = False
    is_playing: bool = False
    ai_ready: bool = False

    # Counters
    inbound_chunks: int = 0
    outbound_chunks: int = 0
    outbound_sequence_number: int = 1
    outbound_timestamp_ms: int = 0

    # Transcript tracking
    caller_transcripts: list[str] = field(default_factory=list)
    agent_replies: list[str] = field(default_factory=list)
    dtmf_digits: list[str] = field(default_factory=list)

    # Call end
    end_reason: str | None = None
    call_start_time: float = field(default_factory=time.monotonic)

    @property
    def log_prefix(self) -> str:
        return (
            f"call_id={self.call_id or 'pending'} "
            f"call_sid={self.call_sid or 'pending'} "
            f"stream_sid={self.stream_sid or 'pending'}"
        )


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

class GeminiLiveConsumer(AsyncJsonWebsocketConsumer):
    """Exotel Voicebot consumer using Gemini Live API for realtime voice.

    Audio flow: Exotel → resample → Gemini Live → resample → Exotel.
    No separate STT or TTS needed.
    """

    state: LiveCallState
    gemini_session: GeminiLiveSession | None
    silence_watchdog: SilenceWatchdog | None

    # ------------------------------------------------------------------
    # WebSocket lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self.state = LiveCallState()
        self.gemini_session = None
        self.silence_watchdog = None
        self.storage = CallStorage()
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._playback_task: asyncio.Task | None = None

        # Parse query parameters
        from urllib.parse import parse_qs
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)

        self.welcome_message = (
            query_params.get("welcome_message", [None])[0]
            or query_params.get("welcome", [None])[0]
        )
        self.aiagent_name = (
            query_params.get("aiagent_name", [None])[0]
            or query_params.get("agent_name", [None])[0]
        )
        self.aiagent_prompt = (
            query_params.get("aiagent_prompt", [None])[0]
            or query_params.get("prompt", [None])[0]
        )
        self.business_url = (
            query_params.get("business_url", [None])[0]
            or query_params.get("website_url", [None])[0]
        )

        await self.accept()
        logger.info(
            "✅ [GeminiLive] Accepted Exotel WebSocket: "
            "agent_name=%s has_prompt=%s",
            self.aiagent_name,
            bool(self.aiagent_prompt),
        )

    async def disconnect(self, close_code: int) -> None:
        self.state.is_stopped = True

        # Set end_reason if not already set (caller hung up)
        if not self.state.end_reason:
            self.state.end_reason = "caller_hangup"

        # Stop silence watchdog
        if self.silence_watchdog:
            await self.silence_watchdog.stop()

        # Stop playback
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()

        # Disconnect Gemini
        if self.gemini_session:
            await self.gemini_session.disconnect()

        # Update call record
        duration_s = time.monotonic() - self.state.call_start_time
        if self.state.call_sid:
            try:
                await self.storage.update_call(
                    call_sid=self.state.call_sid,
                    updates={
                        "status": "completed",
                        "duration": int(duration_s),
                        "end_reason": self.state.end_reason,
                    },
                    call_id=self.state.call_id,
                )
            except Exception as exc:
                logger.error(
                    "%s Failed to update call at disconnect: %s",
                    self.state.log_prefix, exc,
                )

        logger.info(
            "%s 📵 [GeminiLive] Call ended close_code=%s duration=%.1fs "
            "end_reason=%s inbound_chunks=%d",
            self.state.log_prefix,
            close_code,
            duration_s,
            self.state.end_reason,
            self.state.inbound_chunks,
        )

        # Log transcripts
        if self.gemini_session:
            transcripts = self.gemini_session.get_transcripts()
            for i, t in enumerate(transcripts):
                logger.info(
                    "%s 📜 Turn %d: USER=%r | BOT=%r | latency=%.0fms",
                    self.state.log_prefix,
                    i + 1,
                    t.user_text.strip()[:80],
                    t.bot_text.strip()[:80],
                    t.latency_ms,
                )

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        event = str(content.get("event", "")).lower()
        handlers = {
            "connected": self.on_connected,
            "start":     self.on_start,
            "media":     self.on_media,
            "dtmf":      self.on_dtmf,
            "mark":      self.on_mark,
            "clear":     self.on_clear,
            "stop":      self.on_stop,
        }
        handler = handlers.get(event)
        if handler is None:
            logger.error(
                "%s Unsupported event=%r", self.state.log_prefix, event,
            )
            return
        await handler(content)

    async def send_json(self, content: dict[str, Any], close: bool = False) -> None:
        try:
            await super().send_json(content, close=close)
        except Exception:
            logger.exception(
                "%s Failed sending event=%s",
                self.state.log_prefix, content.get("event"),
            )
            raise

    # ------------------------------------------------------------------
    # Exotel event handlers
    # ------------------------------------------------------------------

    async def on_connected(self, content: dict[str, Any]) -> None:
        logger.info("🔌 [GeminiLive] Exotel connected: %s", content)

    async def on_start(self, content: dict[str, Any]) -> None:
        start = content.get("start") or {}
        self.state.stream_sid = content.get("stream_sid") or start.get("stream_sid")
        self.state.call_sid = start.get("call_sid")
        self.state.account_sid = start.get("account_sid")
        self.state.from_number = to_e164(start.get("from"))
        self.state.to_number = to_e164(start.get("to"))
        self.state.media_format = start.get("media_format") or {}

        if not self.state.stream_sid:
            raise ValueError("Exotel start event missing stream_sid")

        self._validate_media_format()

        # Create Call + Profile records
        try:
            call_data = await self.storage.create_call(
                call_sid=self.state.call_sid or "unknown-sid",
                stream_sid=self.state.stream_sid or "unknown-sid",
                from_number=self.state.from_number,
                to_number=self.state.to_number,
                direction="incoming",
            )
            self.state.call_id = call_data.get("id")
        except Exception as exc:
            logger.error(
                "%s Failed to save call record: %s",
                self.state.log_prefix, exc,
            )

        logger.info(
            "%s 📞 [GeminiLive] Stream STARTED from=%s to=%s",
            self.state.log_prefix,
            self.state.from_number,
            self.state.to_number,
        )

        # Build system prompt
        system_prompt = self.aiagent_prompt or settings.ai_system_prompt or QWR_SYSTEM_PROMPT

        # Create Gemini Live session
        self.gemini_session = GeminiLiveSession(
            system_prompt=system_prompt,
            agent_name=self.aiagent_name or settings.ai_agent_name,
            welcome_message=self.welcome_message or settings.ai_welcome_message,
            call_sid=self.state.call_sid or "unknown",
            stream_sid=self.state.stream_sid or "unknown",
            call_id=str(self.state.call_id) if self.state.call_id else None,
            exotel_sample_rate=self._get_sample_rate(),
            on_audio=self._on_gemini_audio,
            on_turn_complete=self._on_gemini_turn_complete,
            on_interrupted=self._on_gemini_interrupted,
        )

        t_connect = time.monotonic()
        try:
            await self.gemini_session.connect()
        except Exception as exc:
            logger.exception(
                "%s ❌ Failed to connect Gemini Live: %s",
                self.state.log_prefix, exc,
            )
            # Cannot proceed without Gemini
            await self.close()
            return

        connect_ms = (time.monotonic() - t_connect) * 1000
        logger.info(
            "%s 🤖 [GeminiLive] Session ready in %.0fms",
            self.state.log_prefix, connect_ms,
        )

        self.state.ai_ready = True

        # Start silence watchdog
        self.silence_watchdog = SilenceWatchdog(
            on_reprompt=self._handle_silence_reprompt,
            on_hangup=self._handle_silence_hangup,
            log_prefix=self.state.log_prefix,
        )
        await self.silence_watchdog.start()

        # Start playback drainer (sends queued audio to Exotel)
        self._playback_task = asyncio.create_task(
            self._playback_loop(),
            name=f"exotel-playback-{self.state.call_sid}",
        )

        # Send greeting prompt
        await self.gemini_session.send_greeting_prompt()

    async def on_media(self, content: dict[str, Any]) -> None:
        if not self.gemini_session or not self.state.ai_ready:
            return

        self.state.inbound_chunks += 1
        media = content.get("media") or {}
        payload_b64: str = media.get("payload", "")

        if not payload_b64:
            return

        try:
            pcm_chunk = base64.b64decode(payload_b64, validate=True)
        except Exception as exc:
            logger.exception(
                "%s Failed to decode media: %s",
                self.state.log_prefix, exc,
            )
            return

        # Detect speech for silence watchdog
        if not _is_silent(pcm_chunk):
            if self.silence_watchdog:
                self.silence_watchdog.on_speech_detected()

        # Forward to Gemini Live (handles resampling internally)
        await self.gemini_session.send_audio(
            pcm_chunk,
            sample_rate=self._get_sample_rate(),
        )

    async def on_dtmf(self, content: dict[str, Any]) -> None:
        dtmf = content.get("dtmf") or {}
        digit = str(dtmf.get("digit", ""))
        if digit:
            self.state.dtmf_digits.append(digit)
        logger.info(
            "%s ☎️ DTMF digit=%s", self.state.log_prefix, digit,
        )
        if digit and self.gemini_session:
            # Send DTMF as text to Gemini
            await self.gemini_session.send_text(
                f"User pressed key {digit} on keypad"
            )
            if self.silence_watchdog:
                self.silence_watchdog.on_speech_detected()

    async def on_mark(self, content: dict[str, Any]) -> None:
        mark_name = (content.get("mark") or {}).get("name", "")
        logger.info("%s 🏷 Mark: %s", self.state.log_prefix, mark_name)

    async def on_clear(self, content: dict[str, Any]) -> None:
        # Exotel sent clear — drain our queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info(
            "%s 🛑 Exotel clear — flushed audio queue",
            self.state.log_prefix,
        )

    async def on_stop(self, content: dict[str, Any]) -> None:
        self.state.is_stopped = True
        logger.info(
            "%s 🛑 Exotel stop: %s", self.state.log_prefix, content.get("stop"),
        )
        await self.close()

    # ------------------------------------------------------------------
    # Gemini Live callbacks
    # ------------------------------------------------------------------

    async def _on_gemini_audio(self, pcm_8khz: bytes) -> None:
        """Called when Gemini sends audio — queue it for Exotel playback."""
        if self.state.is_stopped:
            return
        # Tell watchdog bot is speaking
        if self.silence_watchdog:
            self.silence_watchdog.on_bot_speaking(True)
        self._audio_queue.put_nowait(pcm_8khz)

    async def _on_gemini_turn_complete(self, transcript: LiveTranscript) -> None:
        """Called when a Gemini turn completes — store transcripts."""
        # Tell watchdog bot finished
        if self.silence_watchdog:
            self.silence_watchdog.on_bot_speaking(False)

        user_text = transcript.user_text.strip()
        bot_text = transcript.bot_text.strip()

        if user_text:
            self.state.caller_transcripts.append(user_text)
        if bot_text:
            self.state.agent_replies.append(bot_text)

        # Store transcript turns in DB
        call_sid = self.state.call_sid or ""
        if call_sid:
            try:
                if user_text:
                    await self.storage.insert_transcript_turn(
                        call_sid=call_sid,
                        speaker="user",
                        text=user_text,
                        call_id=self.state.call_id,
                    )
                if bot_text:
                    await self.storage.insert_transcript_turn(
                        call_sid=call_sid,
                        speaker="assistant",
                        text=bot_text,
                        latency_ms=int(transcript.latency_ms),
                        call_id=self.state.call_id,
                    )
            except Exception as exc:
                logger.error(
                    "%s Failed to save transcript turns: %s",
                    self.state.log_prefix, exc,
                )

        # Check for AI-initiated call end
        if bot_text and "[END_CALL" in bot_text:
            import re
            match = re.search(r'\[END_CALL\s+reason="([^"]+)"\]', bot_text)
            reason = match.group(1) if match else "ai_ended"
            logger.info(
                "%s 🔚 AI initiated call end: reason=%s",
                self.state.log_prefix, reason,
            )
            self.state.end_reason = reason
            # Allow final audio to play, then close
            asyncio.create_task(self._delayed_close(2.0))

    async def _on_gemini_interrupted(self) -> None:
        """Called when user barges in — clear queued audio."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if not self.state.is_stopped and self.state.stream_sid:
            try:
                await self.send_json({
                    "event": "clear",
                    "stream_sid": self.state.stream_sid,
                })
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Silence watchdog callbacks
    # ------------------------------------------------------------------

    async def _handle_silence_reprompt(self, message: str) -> None:
        """Send a reprompt via Gemini (it will speak it)."""
        if self.gemini_session and self.gemini_session.is_connected:
            await self.gemini_session.send_text(
                f"The caller has been silent. Say exactly this: \"{message}\""
            )

    async def _handle_silence_hangup(self, farewell: str) -> None:
        """Speak farewell and disconnect due to extended silence."""
        self.state.end_reason = "no_input_timeout"
        if self.gemini_session and self.gemini_session.is_connected:
            await self.gemini_session.send_text(
                f"The caller has been silent for too long. "
                f"Say exactly this: \"{farewell}\""
            )
        # Wait for farewell to play, then close
        asyncio.create_task(self._delayed_close(5.0))

    # ------------------------------------------------------------------
    # Playback: queue → Exotel
    # ------------------------------------------------------------------

    async def _playback_loop(self) -> None:
        """Continuously drain the audio queue and send to Exotel.

        Chunks are 20ms frames paced by asyncio.sleep for real-time
        playback to the caller.
        """
        sample_rate = self._get_sample_rate()
        chunk_bytes = self._get_chunk_bytes()

        try:
            while not self.state.is_stopped:
                # Wait for audio from Gemini
                try:
                    pcm_data = await asyncio.wait_for(
                        self._audio_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                if self.state.is_stopped or not self.state.stream_sid:
                    break

                self.state.is_playing = True

                # Chunk and send
                chunks = list(chunk_pcm(pcm_data, chunk_size=chunk_bytes))
                for chunk in chunks:
                    if self.state.is_stopped:
                        break

                    chunk_b64 = b64_audio(chunk)
                    self.state.outbound_chunks += 1

                    await self.send_json({
                        "event": "media",
                        "stream_sid": self.state.stream_sid,
                        "media": {"payload": chunk_b64},
                    })

                    chunk_dur = chunk_duration_seconds(chunk, sample_rate=sample_rate)
                    self.state.outbound_timestamp_ms += round(chunk_dur * 1000)
                    await asyncio.sleep(chunk_dur)

                self.state.is_playing = False

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception(
                "%s ❌ Playback loop error: %s",
                self.state.log_prefix, exc,
            )
        finally:
            self.state.is_playing = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _delayed_close(self, delay_s: float) -> None:
        """Wait for audio to drain, then close the WebSocket."""
        await asyncio.sleep(delay_s)
        if not self.state.is_stopped:
            self.state.is_stopped = True
            await self.close()

    def _get_sample_rate(self) -> int:
        raw = self.state.media_format.get("sample_rate")
        try:
            sr = int(raw)
        except (TypeError, ValueError):
            return EXOTEL_SAMPLE_RATE_HZ
        return sr if sr > 0 else EXOTEL_SAMPLE_RATE_HZ

    def _get_frame_ms(self) -> int:
        raw = self.state.media_format.get("timestamp_ms")
        try:
            ms = int(raw)
        except (TypeError, ValueError):
            return 20
        return ms if ms > 0 else 20

    def _get_chunk_bytes(self) -> int:
        return (
            self._get_sample_rate()
            * EXOTEL_SAMPLE_WIDTH_BYTES
            * EXOTEL_CHANNELS
            * self._get_frame_ms()
            // 1000
        )

    def _validate_media_format(self) -> None:
        encoding = str(self.state.media_format.get("encoding") or "raw/slin").lower()
        if encoding not in SUPPORTED_EXOTEL_ENCODINGS:
            raise ValueError(f"Unsupported Exotel encoding={encoding!r}")
        sr = self._get_sample_rate()
        if sr not in SUPPORTED_EXOTEL_SAMPLE_RATES:
            raise ValueError(f"Unsupported Exotel sample_rate={sr}")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _is_silent(pcm_chunk: bytes, threshold: int = 200) -> bool:
    """Return True if the PCM chunk RMS energy is below threshold."""
    if len(pcm_chunk) < 2:
        return True
    import struct
    num_samples = len(pcm_chunk) // 2
    try:
        samples = struct.unpack(f"<{num_samples}h", pcm_chunk[:num_samples * 2])
    except struct.error:
        return True
    rms = (sum(s * s for s in samples) / num_samples) ** 0.5
    return rms < threshold
