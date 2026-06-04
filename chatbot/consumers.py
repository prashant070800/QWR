"""WebSocket consumer for real-time text chat.

Handles JSON messages over WebSocket for instant back-and-forth chat.
No audio processing, no STT/TTS — pure text for minimum latency.
"""

from __future__ import annotations

import json
import logging
import uuid

from channels.generic.websocket import AsyncWebSocketConsumer

from .agent import ChatAgent

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebSocketConsumer):
    """WebSocket consumer for text-based chat."""

    async def connect(self):
        self.session_id = str(uuid.uuid4())[:8]
        self.agent = ChatAgent(session_id=self.session_id)
        await self.accept()

        logger.info("Chat session connected session=%s", self.session_id)

        # Send a welcome message
        await self.send(text_data=json.dumps({
            "type": "message",
            "role": "assistant",
            "content": "Hey! I'm Nova, your AI assistant. How can I help you today?",
            "session_id": self.session_id,
        }))

    async def disconnect(self, close_code):
        logger.info(
            "Chat session disconnected session=%s code=%s",
            self.session_id,
            close_code,
        )

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                "type": "error",
                "content": "Invalid JSON",
            }))
            return

        msg_type = data.get("type", "message")

        if msg_type == "message":
            user_text = data.get("content", "").strip()
            if not user_text:
                return

            # Send typing indicator
            await self.send(text_data=json.dumps({"type": "typing", "typing": True}))

            try:
                reply = await self.agent.chat(user_text)

                # Stop typing indicator + send reply
                await self.send(text_data=json.dumps({"type": "typing", "typing": False}))
                await self.send(text_data=json.dumps({
                    "type": "message",
                    "role": "assistant",
                    "content": reply,
                }))
            except Exception as exc:
                logger.exception("Chat error session=%s: %s", self.session_id, exc)
                await self.send(text_data=json.dumps({"type": "typing", "typing": False}))
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "content": "Something went wrong. Please try again.",
                }))

        elif msg_type == "clear":
            self.agent.clear_history()
            await self.send(text_data=json.dumps({
                "type": "cleared",
                "content": "Conversation cleared. How can I help you?",
            }))
