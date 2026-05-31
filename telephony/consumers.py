"""Exotel AgentStream WebSocket integration — full AI voice pipeline.

Flow
----
1. Exotel connects → we accept.
2. Exotel sends "start" → capture call metadata, create QWRAgent,
   stream the hardcoded greeting WAV immediately.
3. Exotel sends "media" → accumulate inbound PCM.
   After configurable silence (STT_SILENCE_CHUNKS), flush buffer to STT.
4. Transcript → QWRAgent.chat() → AI reply text.
5. Reply text → TTS (gtts/google) → PCM → chunked base64 frames to Exotel.

Every outbound audio packet is logged with stream_sid, chunk index, and byte count.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from ai_agent.agent import ConversationTurn, QWRAgent
from ai_agent.config import settings
from ai_agent.stt import transcribe_audio
from ai_agent.tts import synthesize_speech

from .audio import (
    EXOTEL_CHANNELS,
    EXOTEL_SAMPLE_RATE_HZ,
    EXOTEL_SAMPLE_WIDTH_BYTES,
    b64_audio,
    chunk_duration_seconds,
    chunk_pcm,
    generate_tone_pcm,
    load_wav_pcm,
)

logger = logging.getLogger(__name__)

# Greeting text shown in logs — the WAV file is what the caller actually hears
HARDCODED_GREETING = "Welcome to QWR! How can I help you today?"
SUPPORTED_EXOTEL_ENCODINGS = {"raw/slin", "slin", "linear16", "pcm", "base64", ""}
SUPPORTED_EXOTEL_SAMPLE_RATES = {8000, 16000, 24000}
BARGE_IN_SPEECH_CHUNKS = 120

# Path to the hold-music / greeting WAV bundled in the project root
PLEASE_WAIT_WAV: Path = (
    Path(__file__).resolve().parent.parent / "please-wait-while-we-connect-your-call.wav"
)


# ---------------------------------------------------------------------------
# Call state
# ---------------------------------------------------------------------------

@dataclass
class ExotelStreamState:
    """All metadata and buffers for one active Exotel call."""

    # Exotel identifiers
    stream_sid: str | None = None
    call_sid: str | None = None
    account_sid: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    media_format: dict[str, Any] = field(default_factory=dict)

    # Inbound audio accumulation
    inbound_chunks: int = 0
    audio_buffer: bytearray = field(default_factory=bytearray)
    silent_chunk_count: int = 0
    speech_chunk_count: int = 0
    is_processing_stt: bool = False
    caller_transcripts: list[str] = field(default_factory=list)
    agent_replies: list[str] = field(default_factory=list)

    # DTMF
    dtmf_digits: list[str] = field(default_factory=list)

    # Playback
    is_stopped: bool = False
    is_playing: bool = False
    outbound_chunks: int = 0
    outbound_timestamp_ms: int = 0
    outbound_sequence_number: int = 1

    # Logging
    first_media_logged: bool = False
    call_start_time: float = field(default_factory=time.monotonic)

    @property
    def log_prefix(self) -> str:
        return f"call_sid={self.call_sid or 'pending'} stream_sid={self.stream_sid or 'pending'}"


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

class ExotelVoicebotConsumer(AsyncJsonWebsocketConsumer):
    """Exotel Voicebot Applet WebSocket consumer with full AI voice pipeline."""

    state: ExotelStreamState
    playback_task: asyncio.Task | None
    ai_task: asyncio.Task | None
    agent: QWRAgent | None

    # ------------------------------------------------------------------
    # WebSocket lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self.state = ExotelStreamState()
        self.playback_task = None
        self.ai_task = None
        self.agent = None
        await self.accept()
        logger.info("✅ Accepted Exotel WebSocket connection (awaiting 'start' event)")

    async def disconnect(self, close_code: int) -> None:
        self.state.is_stopped = True
        for task in (self.playback_task, self.ai_task):
            if task and not task.done():
                task.cancel()

        duration_s = time.monotonic() - self.state.call_start_time
        logger.info(
            "%s 📵 Call ended close_code=%s duration_s=%.1f "
            "inbound_chunks=%s dtmf=%s",
            self.state.log_prefix,
            close_code,
            duration_s,
            self.state.inbound_chunks,
            "".join(self.state.dtmf_digits),
        )
        self._log_call_summary()

        if self.agent:
            transcript = self.agent.get_transcript()
            logger.info(
                "%s 📜 Call transcript (%d turns):\n%s",
                self.state.log_prefix,
                len(transcript),
                _format_transcript(transcript),
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
                "%s Unsupported Exotel event=%r payload=%s",
                self.state.log_prefix,
                event,
                content,
            )
            raise ValueError(f"Unsupported Exotel event={event!r}")
        await handler(content)

    async def send_json(self, content: dict[str, Any], close: bool = False) -> None:
        logger.debug(
            "%s → Exotel event=%s",
            self.state.log_prefix,
            content.get("event"),
        )
        await super().send_json(content, close=close)

    # ------------------------------------------------------------------
    # Exotel event handlers
    # ------------------------------------------------------------------

    async def on_connected(self, content: dict[str, Any]) -> None:
        logger.info("🔌 Exotel connected event: %s", content)

    async def on_start(self, content: dict[str, Any]) -> None:
        start = content.get("start") or {}
        self.state.stream_sid    = content.get("stream_sid") or start.get("stream_sid")
        self.state.call_sid      = start.get("call_sid")
        self.state.account_sid   = start.get("account_sid")
        self.state.from_number   = start.get("from")
        self.state.to_number     = start.get("to")
        self.state.media_format  = start.get("media_format") or {}
        if not self.state.stream_sid:
            logger.error("%s Exotel start missing stream_sid payload=%s", self.state.log_prefix, content)
            raise ValueError("Exotel start event missing stream_sid")

        self._validate_media_format()

        logger.info(
            "%s 📞 Exotel stream STARTED from=%s to=%s media_format=%s "
            "outbound_frame_bytes=%d outbound_frame_ms=%d",
            self.state.log_prefix,
            self.state.from_number,
            self.state.to_number,
            self.state.media_format,
            self.get_chunk_bytes(),
            self.get_frame_ms(),
        )

        # Create the per-call AI agent
        self.agent = QWRAgent(
            call_sid=self.state.call_sid,
            stream_sid=self.state.stream_sid,
        )

        # Stream greeting immediately (uses the WAV file — guaranteed audio)
        self.playback_task = asyncio.create_task(self._play_greeting())

    async def on_media(self, content: dict[str, Any]) -> None:
        self.state.inbound_chunks += 1
        media = content.get("media") or {}
        payload_b64: str = media.get("payload", "")

        if not self.state.first_media_logged:
            self.state.first_media_logged = True
            logger.info(
                "%s 🎤 FIRST inbound audio chunk=%s timestamp=%s payload_chars=%d",
                self.state.log_prefix,
                media.get("chunk"),
                media.get("timestamp"),
                len(payload_b64),
            )

        logger.debug(
            "%s 🎤 Inbound audio chunk=%s timestamp=%s payload_chars=%d "
            "total_inbound=%d",
            self.state.log_prefix,
            media.get("chunk"),
            media.get("timestamp"),
            len(payload_b64),
            self.state.inbound_chunks,
        )

        if payload_b64:
            try:
                pcm_chunk = base64.b64decode(payload_b64, validate=True)
            except Exception as exc:
                logger.exception(
                    "%s Failed to decode media payload: %s",
                    self.state.log_prefix,
                    exc,
                )
                raise

            if len(pcm_chunk) % EXOTEL_SAMPLE_WIDTH_BYTES != 0:
                logger.error(
                    "%s Inbound PCM byte count is not 16-bit aligned: bytes=%d",
                    self.state.log_prefix,
                    len(pcm_chunk),
                )
                raise ValueError(f"Inbound PCM is not 16-bit aligned: {len(pcm_chunk)} bytes")

            self.state.audio_buffer.extend(pcm_chunk)

            if _is_silent(pcm_chunk):
                self.state.silent_chunk_count += 1
                self.state.speech_chunk_count = 0
            else:
                self.state.silent_chunk_count = 0
                self.state.speech_chunk_count += 1
                self._cancel_playback_for_barge_in()

        sample_rate   = self.get_sample_rate()
        silence_limit = settings.stt_silence_chunks
        min_buf_bytes = sample_rate * 2 * 1  # 1 second of audio minimum

        # Trigger STT when we detect a pause after speech
        if (
            self.state.silent_chunk_count >= silence_limit
            and len(self.state.audio_buffer) >= min_buf_bytes
            and not self.state.is_processing_stt
            and not (self.playback_task and not self.playback_task.done())
        ):
            audio_data = bytes(self.state.audio_buffer)
            self.state.audio_buffer      = bytearray()
            self.state.silent_chunk_count = 0
            self.state.is_processing_stt  = True

            logger.info(
                "%s 🔇 Silence detected — flushing %d bytes to STT",
                self.state.log_prefix,
                len(audio_data),
            )
            self.ai_task = asyncio.create_task(
                self._handle_user_speech(audio_data)
            )

    async def on_dtmf(self, content: dict[str, Any]) -> None:
        dtmf  = content.get("dtmf") or {}
        digit = str(dtmf.get("digit", ""))
        if digit:
            self.state.dtmf_digits.append(digit)
        logger.info(
            "%s ☎️  DTMF digit=%s duration_ms=%s",
            self.state.log_prefix,
            digit,
            dtmf.get("duration"),
        )
        if digit and self.agent:
            self.ai_task = asyncio.create_task(
                self._handle_user_speech(
                    b"", text_override=f"User pressed key {digit} on keypad"
                )
            )

    async def on_mark(self, content: dict[str, Any]) -> None:
        mark_name = (content.get("mark") or {}).get("name", "")
        logger.info("%s 🏷  Mark received: %s", self.state.log_prefix, mark_name)

    async def on_clear(self, content: dict[str, Any]) -> None:
        self._cancel_playback("Exotel clear")
        logger.info("%s 🛑 Exotel clear — stopped local playback", self.state.log_prefix)

    async def on_stop(self, content: dict[str, Any]) -> None:
        self.state.is_stopped = True
        self._cancel_playback("Exotel stop")
        logger.info(
            "%s 🛑 Exotel stop: %s",
            self.state.log_prefix,
            content.get("stop"),
        )
        await self.close()

    # ------------------------------------------------------------------
    # Voice pipeline
    # ------------------------------------------------------------------

    async def _play_greeting(self) -> None:
        """Stream the hardcoded greeting to the caller.

        Strategy:
        1. Try to synthesize greeting text via TTS (gtts/google).
        2. Fall back to the bundled WAV file.
        3. Last resort: generate a synthetic tone (always works).
        """
        sample_rate = self.get_sample_rate()
        log_prefix  = self.state.log_prefix

        logger.info(
            "%s 🎙  Greeting: %r  (TTS provider: %s)",
            log_prefix,
            HARDCODED_GREETING,
            settings.tts_provider,
        )

        # Record greeting in agent history
        if self.agent:
            self.agent._history.append(
                ConversationTurn(speaker="assistant", text=HARDCODED_GREETING)
            )
        self.state.agent_replies.append(HARDCODED_GREETING)

        pcm: bytes = b""

        # --- Attempt TTS synthesis ---
        if settings.tts_provider != "stub":
            try:
                pcm = await synthesize_speech(
                    HARDCODED_GREETING,
                    sample_rate=sample_rate,
                    call_sid=self.state.call_sid or "",
                    stream_sid=self.state.stream_sid or "",
                )
            except Exception as exc:
                logger.exception("%s TTS error: %s — trying WAV fallback", log_prefix, exc)

        # --- Fall back to WAV file if TTS gave us nothing ---
        if not pcm:
            if PLEASE_WAIT_WAV.exists():
                logger.info(
                    "%s 🎵 Using bundled WAV for greeting: %s",
                    log_prefix,
                    PLEASE_WAIT_WAV,
                )
                try:
                    pcm = load_wav_pcm(PLEASE_WAIT_WAV, target_sample_rate=sample_rate)
                except Exception as exc:
                    logger.exception("%s WAV load error: %s", log_prefix, exc)
            else:
                logger.warning(
                    "%s WAV not found at %s — generating tone", log_prefix, PLEASE_WAIT_WAV
                )

        # --- Last resort: synthetic tone ---
        if not pcm:
            pcm = generate_tone_pcm(duration_seconds=3.0, sample_rate=sample_rate)
            logger.info("%s 🔔 Using synthetic tone as greeting fallback", log_prefix)

        await self._stream_pcm_to_exotel(pcm, mark_name="qwr-greeting-complete")

    async def _handle_user_speech(
        self,
        pcm_bytes: bytes,
        *,
        text_override: str | None = None,
    ) -> None:
        """Full pipeline: PCM → STT → LLM → TTS → Exotel stream."""
        try:
            sample_rate = self.get_sample_rate()
            call_sid    = self.state.call_sid or ""
            stream_sid  = self.state.stream_sid or ""

            # Step 1: STT
            if text_override:
                transcript = text_override
            else:
                transcript = await transcribe_audio(
                    pcm_bytes,
                    sample_rate=sample_rate,
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                )

            if not transcript:
                logger.info(
                    "%s Empty transcript — no AI response generated",
                    self.state.log_prefix,
                )
                return

            self.state.caller_transcripts.append(transcript)
            logger.info(
                "%s 📝 CUSTOMER transcript: %r",
                self.state.log_prefix,
                transcript,
            )

            # Step 2: AI agent
            if not self.agent:
                logger.error("%s Agent not initialised", self.state.log_prefix)
                return

            try:
                reply = await self.agent.chat(transcript)
            except Exception as exc:
                logger.exception(
                    "%s Agent failed to generate reply: %s",
                    self.state.log_prefix,
                    exc,
                )
                reply = (
                    "I'm sorry, I had trouble processing that. "
                    "Please tell me how I can help with QWR."
                )
                self.agent._history.append(ConversationTurn(speaker="user", text=transcript))
                self.agent._history.append(ConversationTurn(speaker="assistant", text=reply))
            self.state.agent_replies.append(reply)

            logger.info(
                "%s 🤖 AGENT reply text: %r",
                self.state.log_prefix,
                reply,
            )

            if self.state.is_stopped:
                logger.info(
                    "%s Call already stopped — not synthesizing agent voice",
                    self.state.log_prefix,
                )
                return

            # Step 3: TTS
            pcm = await synthesize_speech(
                reply,
                sample_rate=sample_rate,
                call_sid=call_sid,
                stream_sid=stream_sid,
            )

            logger.info(
                "%s 🔊 TTS output: %d bytes → streaming to Exotel",
                self.state.log_prefix,
                len(pcm),
            )

            if self.state.is_stopped:
                logger.info(
                    "%s Call stopped after TTS — not streaming agent voice",
                    self.state.log_prefix,
                )
                return

            # Step 4: stream audio
            await self._stream_pcm_to_exotel(pcm, mark_name="qwr-reply-complete")

        except asyncio.CancelledError:
            logger.info("%s AI pipeline cancelled", self.state.log_prefix)
            raise
        except Exception as exc:
            logger.exception(
                "%s ❌ Unhandled error in AI pipeline: %s",
                self.state.log_prefix,
                exc,
            )
        finally:
            self.state.is_processing_stt = False

    async def _stream_pcm_to_exotel(
        self,
        pcm: bytes,
        mark_name: str = "qwr-audio-complete",
    ) -> None:
        """Chunk raw PCM and send as Exotel base64 media frames.

        Logs every outbound packet with chunk index and byte count.
        """
        if self.state.is_stopped:
            logger.info(
                "%s Not streaming audio mark=%s because call is stopped",
                self.state.log_prefix,
                mark_name,
            )
            return

        if not self.state.stream_sid:
            logger.error(
                "%s Cannot stream audio — stream_sid not yet known",
                self.state.log_prefix,
            )
            raise RuntimeError("Cannot stream audio before stream_sid is known")

        if not pcm:
            logger.error(
                "%s _stream_pcm_to_exotel called with empty PCM — nothing to send",
                self.state.log_prefix,
            )
            raise ValueError("Cannot stream empty PCM to Exotel")

        if len(pcm) % EXOTEL_SAMPLE_WIDTH_BYTES != 0:
            logger.error(
                "%s Outbound PCM byte count is not 16-bit aligned: bytes=%d mark=%s",
                self.state.log_prefix,
                len(pcm),
                mark_name,
            )
            raise ValueError(f"Outbound PCM is not 16-bit aligned: {len(pcm)} bytes")

        sample_rate  = self.get_sample_rate()
        chunk_bytes  = self.get_chunk_bytes()
        chunks       = list(chunk_pcm(pcm, chunk_size=chunk_bytes))
        total_chunks = len(chunks)
        total_bytes  = len(pcm)
        self.state.is_playing = True

        logger.info(
            "%s 🔊 BEGIN streaming audio → Exotel: "
            "total_chunks=%d total_bytes=%d mark=%s sample_rate=%d "
            "chunk_bytes=%d frame_ms=%d channels=%d sample_width_bytes=%d",
            self.state.log_prefix,
            total_chunks,
            total_bytes,
            mark_name,
            sample_rate,
            chunk_bytes,
            self.get_frame_ms(),
            EXOTEL_CHANNELS,
            EXOTEL_SAMPLE_WIDTH_BYTES,
        )

        try:
            for idx, chunk in enumerate(chunks):
                if self.state.is_stopped:
                    logger.info(
                        "%s Stopping audio stream mark=%s at packet=%d/%d; call is stopped",
                        self.state.log_prefix,
                        mark_name,
                        idx + 1,
                        total_chunks,
                    )
                    return

                chunk_b64  = b64_audio(chunk)
                chunk_dur  = chunk_duration_seconds(chunk, sample_rate=sample_rate)
                self.state.outbound_chunks += 1
                media_chunk = self.state.outbound_chunks
                media_timestamp = self.state.outbound_timestamp_ms
                sequence_number = self.state.outbound_sequence_number
                self.state.outbound_sequence_number += 1

                # ── Audio packet log ──────────────────────────────────────
                logger.debug(
                    "%s 📤 Sending audio packet #%d/%d "
                    "media_chunk=%d timestamp_ms=%d sequence_number=%d "
                    "chunk_bytes=%d b64_chars=%d duration_ms=%.1f",
                    self.state.log_prefix,
                    idx + 1,
                    total_chunks,
                    media_chunk,
                    media_timestamp,
                    sequence_number,
                    len(chunk),
                    len(chunk_b64),
                    chunk_dur * 1000,
                )
                # ─────────────────────────────────────────────────────────

                await self.send_json(
                    {
                        "event":      "media",
                        "sequence_number": sequence_number,
                        "stream_sid": self.state.stream_sid,
                        "media":      {
                            "chunk": media_chunk,
                            "timestamp": str(media_timestamp),
                            "payload": chunk_b64,
                        },
                    }
                )
                self.state.outbound_timestamp_ms += round(chunk_dur * 1000)
                await asyncio.sleep(chunk_dur)

            # Send mark
            sequence_number = self.state.outbound_sequence_number
            self.state.outbound_sequence_number += 1
            if self.state.is_stopped:
                logger.info(
                    "%s Skipping mark=%s because call is stopped",
                    self.state.log_prefix,
                    mark_name,
                )
                return
            await self.send_json(
                {
                    "event":      "mark",
                    "sequence_number": sequence_number,
                    "stream_sid": self.state.stream_sid,
                    "mark":       {"name": mark_name},
                }
            )

            logger.info(
                "%s ✅ Finished streaming audio: chunks_sent=%d mark=%s",
                self.state.log_prefix,
                total_chunks,
                mark_name,
            )

        except asyncio.CancelledError:
            logger.info(
                "%s ⏸  Playback cancelled at chunk=%d/%d mark=%s",
                self.state.log_prefix,
                idx + 1 if "idx" in dir() else 0,
                total_chunks,
                mark_name,
            )
            raise
        finally:
            self.state.is_playing = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cancel_playback_for_barge_in(self) -> None:
        if (
            self.playback_task
            and not self.playback_task.done()
            and self.state.speech_chunk_count >= BARGE_IN_SPEECH_CHUNKS
        ):
            self._cancel_playback("caller speech detected")

    def _cancel_playback(self, reason: str) -> None:
        if self.playback_task and not self.playback_task.done():
            self.playback_task.cancel()
            logger.info("%s Playback cancelled: %s", self.state.log_prefix, reason)
        self.state.is_playing = False

    def _log_call_summary(self) -> None:
        if self.state.caller_transcripts:
            logger.info(
                "%s 🧑 CUSTOMER transcripts (%d):\n%s",
                self.state.log_prefix,
                len(self.state.caller_transcripts),
                _format_lines(self.state.caller_transcripts),
            )
        else:
            logger.info("%s 🧑 CUSTOMER transcripts (0): none", self.state.log_prefix)

        if self.state.agent_replies:
            logger.info(
                "%s 🤖 AGENT replies (%d):\n%s",
                self.state.log_prefix,
                len(self.state.agent_replies),
                _format_lines(self.state.agent_replies),
            )
        else:
            logger.info("%s 🤖 AGENT replies (0): none", self.state.log_prefix)

    def get_sample_rate(self) -> int:
        raw = self.state.media_format.get("sample_rate")
        try:
            sample_rate = int(raw)
        except (TypeError, ValueError):
            return EXOTEL_SAMPLE_RATE_HZ
        if sample_rate <= 0:
            raise ValueError(f"Invalid Exotel sample_rate={sample_rate}")
        return sample_rate

    def get_frame_ms(self) -> int:
        timestamp_ms = self.state.media_format.get("timestamp_ms")
        try:
            frame_ms = int(timestamp_ms)
        except (TypeError, ValueError):
            frame_ms = 20
        if frame_ms <= 0:
            raise ValueError(f"Invalid Exotel frame duration={frame_ms}")
        return frame_ms

    def get_chunk_bytes(self) -> int:
        sample_rate = self.get_sample_rate()
        chunk_bytes = (
            sample_rate
            * EXOTEL_SAMPLE_WIDTH_BYTES
            * EXOTEL_CHANNELS
            * self.get_frame_ms()
            // 1000
        )
        if chunk_bytes <= 0:
            raise ValueError(
                f"Invalid Exotel chunk size sample_rate={sample_rate} frame_ms={self.get_frame_ms()}"
            )
        return chunk_bytes

    def _validate_media_format(self) -> None:
        encoding = str(self.state.media_format.get("encoding") or "raw/slin").lower()
        if encoding not in SUPPORTED_EXOTEL_ENCODINGS:
            logger.error(
                "%s Unsupported Exotel encoding=%r media_format=%s",
                self.state.log_prefix,
                encoding,
                self.state.media_format,
            )
            raise ValueError(f"Unsupported Exotel media encoding={encoding!r}")

        sample_rate = self.get_sample_rate()
        if sample_rate not in SUPPORTED_EXOTEL_SAMPLE_RATES:
            logger.error(
                "%s Unsupported Exotel sample_rate=%d media_format=%s",
                self.state.log_prefix,
                sample_rate,
                self.state.media_format,
            )
            raise ValueError(f"Unsupported Exotel sample_rate={sample_rate}")

        expected_bit_rate = sample_rate * EXOTEL_CHANNELS * EXOTEL_SAMPLE_WIDTH_BYTES * 8
        bit_rate = _parse_exotel_bit_rate(self.state.media_format.get("bit_rate"))
        if bit_rate is not None and bit_rate != expected_bit_rate:
            logger.error(
                "%s Unsupported Exotel bit_rate=%d expected_bit_rate=%d media_format=%s",
                self.state.log_prefix,
                bit_rate,
                expected_bit_rate,
                self.state.media_format,
            )
            raise ValueError(
                f"Unsupported Exotel bit_rate={bit_rate}; expected {expected_bit_rate}"
            )


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _is_silent(pcm_chunk: bytes, threshold: int = 200) -> bool:
    """Return True if the PCM chunk RMS energy is below *threshold*."""
    if len(pcm_chunk) < 2:
        return True
    import struct
    num_samples = len(pcm_chunk) // 2
    try:
        samples = struct.unpack(f"<{num_samples}h", pcm_chunk[: num_samples * 2])
    except struct.error:
        return True
    rms = (sum(s * s for s in samples) / num_samples) ** 0.5
    return rms < threshold


def _parse_exotel_bit_rate(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None

    text = str(raw).strip().lower()
    multiplier = 1
    if text.endswith("kbps"):
        multiplier = 1000
        text = text.removesuffix("kbps")
    elif text.endswith("bps"):
        text = text.removesuffix("bps")

    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid Exotel bit_rate={raw!r}") from exc

    if value <= 0:
        raise ValueError(f"Invalid Exotel bit_rate={raw!r}")
    return value * multiplier


def _format_transcript(turns: list[dict]) -> str:
    lines = []
    for turn in turns:
        role    = turn["speaker"].upper()
        text    = turn["text"]
        latency = f" [{turn['latency_ms']:.0f}ms]" if turn.get("latency_ms") else ""
        lines.append(f"  {role}{latency}: {text}")
    return "\n".join(lines)


def _format_lines(values: list[str]) -> str:
    return "\n".join(f"  {idx}. {value}" for idx, value in enumerate(values, start=1))
