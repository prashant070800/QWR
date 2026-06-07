"""Gemini Live API session manager — audio-in → audio-out in a single WebSocket.

Replaces the traditional STT → LLM → TTS pipeline with Gemini's native
real-time audio model for sub-second latency voice interactions.

Audio specs:
    - Gemini expects: raw 16-bit PCM, 16kHz, mono, little-endian
    - Gemini outputs: raw 16-bit PCM, 24kHz, mono, little-endian
    - Exotel uses:    raw 16-bit PCM, 8kHz, mono, little-endian

This module handles the resampling bridge between Exotel's 8kHz telephony
audio and Gemini Live's 16kHz/24kHz audio.

Usage (from the WebSocket consumer):
    session = GeminiLiveSession(api_key=..., system_prompt=..., ...)
    await session.connect()
    # Forward caller audio
    await session.send_audio(exotel_8khz_pcm_chunk)
    # Receive bot audio + transcriptions via callbacks
    await session.disconnect()
"""

from __future__ import annotations

import asyncio
import audioop
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from ai_agent.config import settings

logger = logging.getLogger(__name__)

# Audio constants
EXOTEL_SAMPLE_RATE = 8000
GEMINI_INPUT_SAMPLE_RATE = 16000
GEMINI_OUTPUT_SAMPLE_RATE = 24000
SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM


def resample_pcm(pcm: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample 16-bit mono PCM from one sample rate to another using audioop."""
    if from_rate == to_rate or not pcm:
        return pcm
    converted, _ = audioop.ratecv(
        pcm, SAMPLE_WIDTH_BYTES, 1, from_rate, to_rate, None
    )
    return converted


@dataclass
class LiveTranscript:
    """Captures transcriptions from a Gemini Live turn."""
    user_text: str = ""
    bot_text: str = ""
    turn_start_monotonic: float = 0.0
    first_audio_monotonic: float | None = None

    @property
    def latency_ms(self) -> float:
        """Time from turn start to first bot audio byte."""
        if self.first_audio_monotonic and self.turn_start_monotonic:
            return (self.first_audio_monotonic - self.turn_start_monotonic) * 1000
        return 0.0


class GeminiLiveSession:
    """Manages a persistent Gemini Live API session for one phone call.

    One instance per call. Thread/task safety: designed for single asyncio
    consumer task, same as QWRAgent.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        system_prompt: str,
        agent_name: str | None = None,
        welcome_message: str | None = None,
        call_sid: str = "unknown",
        stream_sid: str = "unknown",
        call_id: str | None = None,
        caller_profile: dict | None = None,
        exotel_sample_rate: int = EXOTEL_SAMPLE_RATE,
        on_audio: Callable[[bytes], Awaitable[None]] | None = None,
        on_turn_complete: Callable[[LiveTranscript], Awaitable[None]] | None = None,
        on_interrupted: Callable[[], Awaitable[None]] | None = None,
        on_end_call: Callable[[str], Awaitable[None]] | None = None,
        on_mode_selected: Callable[[str], Awaitable[None]] | None = None,
        on_profile_updated: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        self._api_key = api_key or settings.gemini_api_key
        self._model = model or settings.gemini_live_model
        self._system_prompt = system_prompt
        self._agent_name = agent_name
        self._welcome_message = welcome_message
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        self.call_id = call_id or "unknown"
        self._caller_profile = caller_profile
        self._exotel_sample_rate = exotel_sample_rate or EXOTEL_SAMPLE_RATE

        # Callbacks — the consumer wires these to stream audio to Exotel
        self._on_audio = on_audio
        self._on_turn_complete = on_turn_complete
        self._on_interrupted = on_interrupted
        self._on_end_call = on_end_call
        self._on_mode_selected = on_mode_selected
        self._on_profile_updated = on_profile_updated

        # Session state
        self._client = None
        self._connect_cm = None
        self._session = None
        self._genai_types = None
        self._receive_task: asyncio.Task | None = None
        self._connected = False
        self._current_transcript = LiveTranscript()
        self._turn_transcripts: list[LiveTranscript] = []
        self._send_count: int = 0

        self._log_prefix = (
            f"call_id={self.call_id} call_sid={self.call_sid} "
            f"stream_sid={self.stream_sid}"
        )

    async def connect(self) -> None:
        """Establish the Gemini Live WebSocket session."""
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ImportError(
                "google-genai SDK is required for Gemini Live. "
                "Run: pip install google-genai"
            ) from exc

        api_key = self._api_key.strip("'\"")
        client = genai.Client(api_key=api_key)

        # Build system instruction
        system_instruction = self._system_prompt
        if self._agent_name:
            system_instruction = (
                f"Your name is {self._agent_name}. "
                f"Speak as {self._agent_name}.\n{system_instruction}"
            )

        # Inject caller identity context
        profile = self._caller_profile or {}
        caller_name = profile.get("name")
        caller_phone = profile.get("phone", "unknown")
        is_known = bool(caller_name and caller_name.strip())

        if is_known:
            system_instruction += (
                f"\n\n--- CALLER IDENTITY ---\n"
                f"This is a KNOWN caller. Greet them by name.\n"
                f"Name: {caller_name}\n"
                f"Phone: {caller_phone}\n"
                f"Company: {profile.get('company') or 'not provided'}\n"
                f"Role: {profile.get('role') or 'not provided'}\n"
                f"City: {profile.get('city') or 'not provided'}\n"
                f"Use this context to personalize the conversation. "
                f"You may still ask if any details have changed.\n"
            )
        else:
            system_instruction += (
                f"\n\n--- CALLER IDENTITY ---\n"
                f"This is an UNKNOWN caller (phone: {caller_phone}).\n"
                f"After greeting and mode selection, ask if they'd like to "
                f"share some details or stay anonymous. Say something like: "
                f"'I don\'t think we\'ve spoken before. Would you like to "
                f"tell me your name and a bit about yourself, or would you "
                f"prefer to stay anonymous? You can also press 1 for yes or "
                f"2 for no.'\n"
                f"\n"
                f"If they agree, run a short INTAKE — collect their name, "
                f"company, role, city, and reason for calling through natural "
                f"conversation (don\'t read a form). Extract details from "
                f"what they say and call the update_profile tool to save them. "
                f"Leave fields null if not mentioned — never guess or invent.\n"
                f"\n"
                f"If they decline, say 'No problem, let\'s continue' and "
                f"proceed in anonymous mode.\n"
                f"Once you learn their name, use it in later turns.\n"
            )

        system_instruction += (
            "\n\n--- VOICE CALL BEHAVIOR ---\n"
            "You are on a live phone call. Follow these rules:\n"
            "- If you cannot understand the caller or the audio is unclear, "
            "say something like 'Sorry, I didn’t quite catch that — could you "
            "repeat?' Do NOT stay silent.\n"
            "- If the caller's response is too short or ambiguous, ask a brief "
            "clarifying question.\n"
            "- Keep responses concise — this is a phone call, not a text chat.\n"
            "- Speak naturally and conversationally, not like reading a script.\n"
            "\n--- MODE SELECTION ---\n"
            "Early in the call, AFTER greeting the caller, offer them four "
            "conversation modes. Say something like: "
            "'I can chat with you in different styles. You can pick one by "
            "saying its name or pressing the number on your keypad: "
            "1 for Think, 2 for Challenge, 3 for Explore, or 4 for Guide. "
            "Which would you like?'\n"
            "\n"
            "Accept BOTH spoken answers (\"I want Challenge mode\", \"number two\", "
            "\"think\") AND keypad input (\"User pressed key 2\" means Challenge). "
            "If the caller says something unclear, re-prompt once. "
            "If they don't choose, default to Think mode.\n"
            "\n"
            "When the caller picks a mode, call the select_mode tool, then "
            "confirm: 'Great, we\'re in [mode] mode.' Then SHIFT your behavior "
            "to match that mode\'s style as defined below.\n"
            "\n"
            "MODE DEFINITIONS:\n"
            "\n"
            "1 — THINK:\n"
            "A thinking partner — a sharp, curious friend you can think out loud "
            "with. Engage with the substance of what the caller says: react, "
            "agree, disagree, build on it, share real opinions with reasoning. "
            "Ask a question only when you genuinely need more to be useful, one "
            "at a time. Don\'t bounce every statement back as a question; don\'t "
            "play therapist. Be brief when they\'re brief, expand when they expand.\n"
            "\n"
            "2 — CHALLENGE:\n"
            "Devil\'s advocate, on the caller\'s side but refusing to nod along. "
            "Pressure-test their claim with real, specific objections drawn from "
            "what they actually said. Ask for evidence; surface hidden assumptions; "
            "steelman the counter-argument. Concede honestly when they make a good "
            "point ('Fair.'), then ask the next harder question. Don\'t nitpick "
            "for cheap points, don\'t be contrarian forever, don\'t get hostile.\n"
            "\n"
            "3 — EXPLORE:\n"
            "Voice-based learning. The caller names a topic; explain it "
            "conversationally in 90-second to 2-minute chunks, then pause and "
            "check in ('Want me to go deeper, or shift?'). Use analogies and "
            "concrete examples, not jargon or bullet-point delivery. Admit what\'s "
            "contested vs settled, and say 'honestly, I don\'t know' rather than "
            "bluffing. Talk more than you listen — but never for more than two "
            "minutes without checking in.\n"
            "\n"
            "4 — GUIDE:\n"
            "A steadier, slower hand — for working through a decision between "
            "options, or sitting with something difficult. Slow the pace, offer "
            "structure when the caller is overwhelmed, gently name the shape of "
            "the problem ('It sounds like X matters more to you than Y'). You may "
            "offer a frame, but do not give direct advice ('you should do X' is "
            "out). Acknowledge difficulty briefly, then keep moving. Walk "
            "alongside; don\'t lead, don\'t decide for them.\n"
            "\n--- CALL CONTROL ---\n"
            "You have an end_call tool. Use it ONLY when:\n"
            "- The caller says goodbye, thanks you, or confirms they are done.\n"
            "- The caller explicitly asks to end the call.\n"
            "- The conversation has naturally concluded with no more questions.\n"
            "Always say a brief farewell BEFORE calling end_call.\n"
            "Never call end_call mid-conversation or without a clear signal "
            "from the caller.\n"
        )

        # Define function tools
        tools = types.Tool(
            function_declarations=[
                # --- select_mode ---
                types.FunctionDeclaration(
                    name="select_mode",
                    description=(
                        "Set the conversation mode after the caller picks one. "
                        "Call this when the caller chooses Think, Challenge, "
                        "Explore, or Guide — by voice or keypad."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "mode": types.Schema(
                                type="STRING",
                                description=(
                                    "The selected mode. Must be one of: "
                                    "'think', 'challenge', 'explore', 'guide'"
                                ),
                                enum=["think", "challenge", "explore", "guide"],
                            ),
                        },
                        required=["mode"],
                    ),
                ),
                # --- update_profile ---
                types.FunctionDeclaration(
                    name="update_profile",
                    description=(
                        "Save or update the caller's profile details extracted "
                        "from natural conversation. Call this after the caller "
                        "shares their name, company, role, city, or reason for "
                        "calling. Only include fields the caller actually "
                        "mentioned — omit or set to null if not provided."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "name": types.Schema(
                                type="STRING",
                                description="Caller's full name",
                            ),
                            "company": types.Schema(
                                type="STRING",
                                description="Caller's company or organization",
                            ),
                            "role": types.Schema(
                                type="STRING",
                                description="Caller's job title or role",
                            ),
                            "city": types.Schema(
                                type="STRING",
                                description="Caller's city",
                            ),
                        },
                    ),
                ),
                # --- end_call ---
                types.FunctionDeclaration(
                    name="end_call",
                    description=(
                        "End the phone call. Call this AFTER saying goodbye "
                        "when the caller wants to hang up or the conversation "
                        "is complete."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "reason": types.Schema(
                                type="STRING",
                                description=(
                                    "Why the call is ending. Examples: "
                                    "'conversation_complete', 'caller_goodbye', "
                                    "'caller_request'"
                                ),
                            ),
                        },
                        required=["reason"],
                    ),
                ),
            ]
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=system_instruction)]
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[tools],
        )

        logger.info(
            "%s 🔌 Connecting to Gemini Live API model=%s",
            self._log_prefix,
            self._model,
        )

        self._client = client
        self._genai_types = types

        t_connect = time.monotonic()
        self._connect_cm = client.aio.live.connect(
            model=self._model, config=config
        )
        self._session = await self._connect_cm.__aenter__()
        connect_ms = (time.monotonic() - t_connect) * 1000
        self._connected = True

        logger.info(
            "%s ✅ Gemini Live session connected in %.0fms model=%s",
            self._log_prefix,
            connect_ms,
            self._model,
        )

        # Start the background receive loop
        self._receive_task = asyncio.create_task(
            self._receive_loop(), name=f"gemini-live-recv-{self.call_sid}"
        )

    async def disconnect(self) -> None:
        """Close the Gemini Live session."""
        self._connected = False

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._connect_cm:
            try:
                await self._connect_cm.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning(
                    "%s Error closing Gemini Live session: %s",
                    self._log_prefix, exc,
                )
            self._connect_cm = None
            self._session = None

        logger.info(
            "%s 📵 Gemini Live session disconnected turns=%d",
            self._log_prefix,
            len(self._turn_transcripts),
        )

    async def send_audio(
        self,
        exotel_pcm: bytes,
        *,
        sample_rate: int | None = None,
    ) -> None:
        """Send Exotel PCM audio to Gemini (resampled to 16kHz).

        Call this for every inbound Exotel media chunk.
        """
        if not self._session or not self._connected or not self._genai_types:
            return

        input_sample_rate = sample_rate or self._exotel_sample_rate
        pcm_16khz = resample_pcm(
            exotel_pcm, input_sample_rate, GEMINI_INPUT_SAMPLE_RATE
        )

        self._send_count += 1

        try:
            await self._session.send_realtime_input(
                audio=self._genai_types.Blob(
                    data=pcm_16khz,
                    mime_type="audio/pcm;rate=16000",
                )
            )
        except Exception as exc:
            if self._send_count <= 3 or self._send_count % 500 == 0:
                logger.error(
                    "%s Failed to send audio #%d to Gemini Live: %s",
                    self._log_prefix, self._send_count, exc,
                )

    async def send_text(self, text: str) -> None:
        """Send a text message to Gemini Live (e.g. DTMF override)."""
        if not self._session or not self._connected:
            return

        try:
            await self._session.send_realtime_input(text=text)
        except Exception as exc:
            logger.error(
                "%s Failed to send text to Gemini Live: %s",
                self._log_prefix, exc,
            )

    async def send_greeting_prompt(self) -> None:
        """Ask Gemini to speak the opening greeting.

        If a welcome_message is configured, send it as a text prompt so
        Gemini speaks it in its natural voice. Otherwise ask Gemini to
        generate one.
        """
        if not self._session or not self._connected:
            return

        self._current_transcript = LiveTranscript(
            turn_start_monotonic=time.monotonic()
        )

        caller_name = self._caller_name()

        if caller_name:
            base_greeting = (
                self._welcome_message
                or "Welcome to QWR, how can I help you?"
            )
            prompt = (
                "Say exactly this to the caller as your greeting: "
                f"\"Hi {caller_name}. {base_greeting}\""
            )
        elif self._welcome_message:
            prompt = (
                f"Say exactly this to the caller as your greeting: "
                f"\"{self._welcome_message}\""
            )
        else:
            prompt = (
                "The phone call has just connected. Greet the caller warmly "
                "as a helpful representative. Keep it under 18 words and ask "
                "how you can help."
            )

        try:
            await self._session.send_realtime_input(text=prompt)
            logger.info(
                "%s 🎙 Greeting prompt sent to Gemini Live",
                self._log_prefix,
            )
        except Exception as exc:
            logger.error(
                "%s Failed to send greeting prompt: %s",
                self._log_prefix, exc,
            )

    def _caller_name(self) -> str | None:
        """Return a clean caller name if this profile already has one."""
        raw_name = (self._caller_profile or {}).get("name")
        if not isinstance(raw_name, str):
            return None

        name = " ".join(raw_name.split())
        return name or None

    def get_transcripts(self) -> list[LiveTranscript]:
        """Return all completed turn transcripts for this call."""
        return list(self._turn_transcripts)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    # ------------------------------------------------------------------
    # Background receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Continuously read responses from Gemini Live and dispatch callbacks.

        Runs as a background task for the lifetime of the call.
        """
        if not self._session:
            return

        response_count = 0
        try:
            while self._connected:
                turn_response_count = 0

                async for response in self._session.receive():
                    if not self._connected:
                        break

                    response_count += 1
                    turn_response_count += 1

                    # --- Tool calls (e.g. end_call) ---
                    if response.tool_call:
                        await self._handle_tool_call(response.tool_call)
                        continue

                    content = response.server_content
                    if content is None:
                        # Non-content response — log it
                        if response_count <= 5 or response_count % 100 == 0:
                            logger.debug(
                                "%s 📡 Gemini recv #%d (non-content): %s",
                                self._log_prefix,
                                response_count,
                                type(response).__name__,
                            )
                        continue

                    # --- Audio data from model ---
                    if content.model_turn and content.model_turn.parts:
                        for part in content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                await self._handle_audio_chunk(
                                    part.inline_data.data
                                )

                    # --- Input transcription (what the user said) ---
                    if content.input_transcription:
                        text = content.input_transcription.text or ""
                        if text.strip():
                            self._current_transcript.user_text += text
                            # New user speech = start of a new turn
                            if not self._current_transcript.turn_start_monotonic:
                                self._current_transcript.turn_start_monotonic = (
                                    time.monotonic()
                                )
                            logger.info(
                                "%s 🎤 User transcription: %r",
                                self._log_prefix,
                                text.strip()[:100],
                            )

                    # --- Output transcription (what the bot said) ---
                    if content.output_transcription:
                        text = content.output_transcription.text or ""
                        if text.strip():
                            self._current_transcript.bot_text += text

                    # --- Turn complete ---
                    if content.turn_complete:
                        await self._handle_turn_complete()

                    # --- Interrupted (barge-in) ---
                    if content.interrupted:
                        logger.info(
                            "%s 🛑 Gemini Live: barge-in detected",
                            self._log_prefix,
                        )
                        if self._on_interrupted:
                            await self._on_interrupted()

                if self._connected:
                    logger.debug(
                        "%s Gemini Live turn receive completed responses=%d; "
                        "waiting for next turn",
                        self._log_prefix,
                        turn_response_count,
                    )
                    if turn_response_count == 0:
                        await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            logger.info(
                "%s Gemini Live receive loop cancelled (responses=%d)",
                self._log_prefix,
                response_count,
            )
        except Exception as exc:
            logger.exception(
                "%s ❌ Gemini Live receive loop error (responses=%d): %s",
                self._log_prefix, response_count, exc,
            )
            self._connected = False
        finally:
            logger.info(
                "%s Gemini Live receive loop ended total_responses=%d",
                self._log_prefix,
                response_count,
            )

    async def _handle_audio_chunk(self, gemini_24khz_pcm: bytes) -> None:
        """Process a chunk of audio from Gemini (24kHz) → resample → callback."""
        # Track first-audio latency
        if self._current_transcript.first_audio_monotonic is None:
            self._current_transcript.first_audio_monotonic = time.monotonic()

        # Resample 24kHz → Exotel's negotiated sample rate.
        exotel_pcm = resample_pcm(
            gemini_24khz_pcm, GEMINI_OUTPUT_SAMPLE_RATE, self._exotel_sample_rate
        )

        if self._on_audio and exotel_pcm:
            await self._on_audio(exotel_pcm)

    async def _handle_turn_complete(self) -> None:
        """Process a completed turn — log, store transcript, notify consumer."""
        transcript = self._current_transcript

        if transcript.user_text.strip() or transcript.bot_text.strip():
            self._turn_transcripts.append(transcript)

            logger.info(
                "%s 💬 Turn #%d | USER: %s | BOT: %s | Latency: %.0fms",
                self._log_prefix,
                len(self._turn_transcripts),
                transcript.user_text.strip() or "[greeting/prompt]",
                transcript.bot_text.strip()[:100] or "[audio only]",
                transcript.latency_ms,
            )

        if self._on_turn_complete:
            await self._on_turn_complete(transcript)

        # Reset for next turn
        self._current_transcript = LiveTranscript()

    async def _handle_tool_call(self, tool_call: Any) -> None:
        """Process tool calls from Gemini (select_mode, end_call).

        For each tool call:
        1. Log it
        2. Send the function response back (required by protocol)
        3. Notify the consumer via callback
        """
        if not self._session or not self._genai_types:
            return

        for fc in tool_call.function_calls:
            logger.info(
                "%s 🛠 Gemini called tool=%s args=%s",
                self._log_prefix,
                fc.name,
                fc.args,
            )

            if fc.name == "select_mode":
                mode = (fc.args or {}).get("mode", "think")
                logger.info(
                    "%s 🎯 Mode selected: %s",
                    self._log_prefix, mode,
                )

                # Send tool response back
                try:
                    await self._session.send_tool_response(
                        function_responses=[
                            self._genai_types.FunctionResponse(
                                name=fc.name,
                                id=fc.id,
                                response={
                                    "status": "mode_set",
                                    "mode": mode,
                                    "message": f"Mode set to {mode}. Shift your behavior now.",
                                },
                            )
                        ]
                    )
                except Exception as exc:
                    logger.warning(
                        "%s Failed to send select_mode response: %s",
                        self._log_prefix, exc,
                    )

                # Notify consumer to store mode
                if self._on_mode_selected:
                    await self._on_mode_selected(mode)

            elif fc.name == "update_profile":
                args = fc.args or {}
                # Filter out None/empty values
                profile_updates = {
                    k: v for k, v in args.items()
                    if v and isinstance(v, str) and v.strip()
                }
                logger.info(
                    "%s 👤 Profile update: %s",
                    self._log_prefix, profile_updates,
                )

                # Send tool response back
                try:
                    await self._session.send_tool_response(
                        function_responses=[
                            self._genai_types.FunctionResponse(
                                name=fc.name,
                                id=fc.id,
                                response={
                                    "status": "profile_updated",
                                    "fields": list(profile_updates.keys()),
                                },
                            )
                        ]
                    )
                except Exception as exc:
                    logger.warning(
                        "%s Failed to send update_profile response: %s",
                        self._log_prefix, exc,
                    )

                # Notify consumer to persist
                if self._on_profile_updated and profile_updates:
                    await self._on_profile_updated(profile_updates)

            elif fc.name == "end_call":
                reason = (fc.args or {}).get("reason", "ai_ended")

                # Send tool response back (Gemini protocol requires it)
                try:
                    await self._session.send_tool_response(
                        function_responses=[
                            self._genai_types.FunctionResponse(
                                name=fc.name,
                                id=fc.id,
                                response={"status": "call_ending", "reason": reason},
                            )
                        ]
                    )
                except Exception as exc:
                    logger.warning(
                        "%s Failed to send end_call response: %s",
                        self._log_prefix, exc,
                    )

                # Notify consumer to disconnect
                if self._on_end_call:
                    await self._on_end_call(reason)
            else:
                logger.warning(
                    "%s Unknown tool call: %s", self._log_prefix, fc.name,
                )
