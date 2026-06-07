"""Silence watchdog — graduated no-input recovery for voice calls.

Tracks extended silence from the caller and triggers graduated recovery:
    1st timeout  → gentle reprompt ("I'm still here...")
    2nd timeout  → explicit check ("Would you like to continue?")
    3rd timeout  → farewell + disconnect

The watchdog runs as an asyncio background task and calls back into the
consumer to speak reprompts or disconnect the call.

Usage:
    watchdog = SilenceWatchdog(
        on_reprompt=my_reprompt_callback,
        on_hangup=my_hangup_callback,
    )
    await watchdog.start()
    # Call watchdog.on_speech_detected() whenever caller speaks
    # Call watchdog.stop() on disconnect
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable

from ai_agent.config import settings

logger = logging.getLogger(__name__)

# Graduated reprompt messages
REPROMPT_MESSAGES = [
    "I'm still here. Take your time, or let me know how I can help.",
    "I didn't hear anything. Would you like to continue, or shall I end the call?",
    "It seems like you may have stepped away. I'll end the call now. Feel free to call back anytime!",
]


class SilenceWatchdog:
    """Watches for extended caller silence and triggers recovery actions.

    Create one per call. Reset on every speech detection.
    """

    def __init__(
        self,
        *,
        on_reprompt: Callable[[str], Awaitable[None]],
        on_hangup: Callable[[str], Awaitable[None]],
        initial_timeout_s: float | None = None,
        reprompt_timeout_s: float | None = None,
        max_no_input: int | None = None,
        log_prefix: str = "",
    ) -> None:
        self._on_reprompt = on_reprompt
        self._on_hangup = on_hangup
        self._initial_timeout = initial_timeout_s or settings.silence_initial_timeout_s
        self._reprompt_timeout = reprompt_timeout_s or settings.silence_reprompt_timeout_s
        self._max_no_input = max_no_input or settings.silence_max_no_input
        self._log_prefix = log_prefix

        self._no_input_count = 0
        self._watchdog_task: asyncio.Task | None = None
        self._running = False
        self._last_speech_time = time.monotonic()
        self._is_bot_speaking = False

    async def start(self) -> None:
        """Begin watching for silence."""
        self._running = True
        self._last_speech_time = time.monotonic()
        self._restart_timer()
        logger.info(
            "%s SilenceWatchdog started initial_timeout=%.0fs "
            "reprompt_timeout=%.0fs max_no_input=%d",
            self._log_prefix,
            self._initial_timeout,
            self._reprompt_timeout,
            self._max_no_input,
        )

    async def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
        self._watchdog_task = None

    def on_speech_detected(self) -> None:
        """Reset the silence timer — caller is speaking."""
        self._last_speech_time = time.monotonic()
        self._no_input_count = 0
        self._restart_timer()

    def on_bot_speaking(self, speaking: bool) -> None:
        """Track bot playback state — don't timeout while bot is talking."""
        self._is_bot_speaking = speaking
        if not speaking:
            # Bot finished talking — restart timer for caller response
            self._last_speech_time = time.monotonic()
            self._restart_timer()

    def _restart_timer(self) -> None:
        """Cancel existing timer and start a new one."""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        if self._running:
            timeout = (
                self._initial_timeout
                if self._no_input_count == 0
                else self._reprompt_timeout
            )
            self._watchdog_task = asyncio.create_task(
                self._timeout_handler(timeout)
            )

    async def _timeout_handler(self, timeout: float) -> None:
        """Wait for silence timeout, then trigger recovery action."""
        try:
            await asyncio.sleep(timeout)

            # Don't trigger while bot is speaking
            if self._is_bot_speaking:
                return

            if not self._running:
                return

            self._no_input_count += 1

            if self._no_input_count >= self._max_no_input:
                # Final timeout → hangup
                farewell = REPROMPT_MESSAGES[-1]
                logger.info(
                    "%s ⏰ Silence watchdog: max no-input reached (%d/%d) — "
                    "hanging up",
                    self._log_prefix,
                    self._no_input_count,
                    self._max_no_input,
                )
                await self._on_hangup(farewell)
            else:
                # Intermediate timeout → reprompt
                msg_idx = min(self._no_input_count - 1, len(REPROMPT_MESSAGES) - 2)
                reprompt = REPROMPT_MESSAGES[msg_idx]
                logger.info(
                    "%s ⏰ Silence watchdog: no-input #%d/%d — reprompting",
                    self._log_prefix,
                    self._no_input_count,
                    self._max_no_input,
                )
                await self._on_reprompt(reprompt)
                # Restart timer for next timeout
                self._restart_timer()

        except asyncio.CancelledError:
            pass
