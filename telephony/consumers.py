"""Exotel AgentStream WebSocket integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .audio import EXOTEL_SAMPLE_RATE_HZ, b64_audio, chunk_duration_seconds, chunk_pcm, generate_tone_pcm


logger = logging.getLogger(__name__)


@dataclass
class ExotelStreamState:
    stream_sid: str | None = None
    call_sid: str | None = None
    account_sid: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    media_format: dict[str, Any] = field(default_factory=dict)
    inbound_chunks: int = 0
    dtmf_digits: list[str] = field(default_factory=list)
    is_playing: bool = False


class ExotelVoicebotConsumer(AsyncJsonWebsocketConsumer):
    """Handle Exotel Voicebot Applet events over a JSON WebSocket.

    Exotel sends JSON events: connected, start, media, dtmf, mark, clear, stop.
    For this first milestone, we answer the start event with 10 seconds of
    little-endian signed 16-bit mono PCM audio encoded as base64 media frames.
    """

    state: ExotelStreamState
    playback_task: asyncio.Task | None

    async def connect(self) -> None:
        self.state = ExotelStreamState()
        self.playback_task = None
        await self.accept()
        logger.info("Accepted Exotel websocket connection")

    async def disconnect(self, close_code: int) -> None:
        if self.playback_task and not self.playback_task.done():
            self.playback_task.cancel()
        logger.info(
            "Disconnected Exotel websocket stream_sid=%s close_code=%s inbound_chunks=%s dtmf=%s",
            self.state.stream_sid,
            close_code,
            self.state.inbound_chunks,
            "".join(self.state.dtmf_digits),
        )

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        event = str(content.get("event", "")).lower()
        handlers = {
            "connected": self.on_connected,
            "start": self.on_start,
            "media": self.on_media,
            "dtmf": self.on_dtmf,
            "mark": self.on_mark,
            "clear": self.on_clear,
            "stop": self.on_stop,
        }

        handler = handlers.get(event)
        if handler is None:
            logger.warning("Ignoring unsupported Exotel event: %s payload=%s", event, content)
            return

        await handler(content)

    async def send_json(self, content: dict[str, Any], close: bool = False) -> None:
        logger.debug("Sending Exotel event=%s stream_sid=%s", content.get("event"), self.state.stream_sid)
        await super().send_json(content, close=close)

    async def on_connected(self, content: dict[str, Any]) -> None:
        logger.info("Exotel connected event received: %s", content)

    async def on_start(self, content: dict[str, Any]) -> None:
        start = content.get("start") or {}
        self.state.stream_sid = content.get("stream_sid") or start.get("stream_sid")
        self.state.call_sid = start.get("call_sid")
        self.state.account_sid = start.get("account_sid")
        self.state.from_number = start.get("from")
        self.state.to_number = start.get("to")
        self.state.media_format = start.get("media_format") or {}

        logger.info(
            "Exotel stream started stream_sid=%s call_sid=%s from=%s to=%s media=%s",
            self.state.stream_sid,
            self.state.call_sid,
            self.state.from_number,
            self.state.to_number,
            self.state.media_format,
        )

        self.playback_task = asyncio.create_task(self.play_music())

    async def on_media(self, content: dict[str, Any]) -> None:
        self.state.inbound_chunks += 1
        media = content.get("media") or {}
        logger.debug(
            "Inbound Exotel media stream_sid=%s chunk=%s timestamp=%s payload_bytes_b64=%s",
            self.state.stream_sid,
            media.get("chunk"),
            media.get("timestamp"),
            len(media.get("payload", "")),
        )

    async def on_dtmf(self, content: dict[str, Any]) -> None:
        dtmf = content.get("dtmf") or {}
        digit = str(dtmf.get("digit", ""))
        if digit:
            self.state.dtmf_digits.append(digit)
        logger.info("Received DTMF digit=%s duration_ms=%s", digit, dtmf.get("duration"))

    async def on_mark(self, content: dict[str, Any]) -> None:
        logger.info("Received Exotel mark: %s", content.get("mark"))

    async def on_clear(self, content: dict[str, Any]) -> None:
        if self.playback_task and not self.playback_task.done():
            self.playback_task.cancel()
        self.state.is_playing = False
        logger.info("Received Exotel clear; stopped local playback")

    async def on_stop(self, content: dict[str, Any]) -> None:
        logger.info("Received Exotel stop: %s", content.get("stop"))
        await self.close()

    async def play_music(self) -> None:
        if not self.state.stream_sid:
            logger.warning("Cannot play media before Exotel stream_sid is known")
            return

        self.state.is_playing = True
        sample_rate = self.get_sample_rate()
        pcm = generate_tone_pcm(duration_seconds=10.0, sample_rate=sample_rate)

        try:
            for chunk in chunk_pcm(pcm):
                await self.send_json(
                    {
                        "event": "media",
                        "stream_sid": self.state.stream_sid,
                        "media": {"payload": b64_audio(chunk)},
                    }
                )
                await asyncio.sleep(chunk_duration_seconds(chunk, sample_rate=sample_rate))

            await self.send_json(
                {
                    "event": "mark",
                    "stream_sid": self.state.stream_sid,
                    "mark": {"name": "qwr-demo-music-complete"},
                }
            )
        except asyncio.CancelledError:
            logger.info("Exotel playback cancelled stream_sid=%s", self.state.stream_sid)
        finally:
            self.state.is_playing = False

    def get_sample_rate(self) -> int:
        raw_sample_rate = self.state.media_format.get("sample_rate")
        try:
            return int(raw_sample_rate)
        except (TypeError, ValueError):
            return EXOTEL_SAMPLE_RATE_HZ
