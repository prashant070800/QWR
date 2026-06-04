import asyncio
import time
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from ai_agent.agent import QWRAgent

class LatencySilenceTests(IsolatedAsyncioTestCase):
    @patch("ai_agent.providers.factory.get_llm_provider")
    async def test_agent_chat_returns_empty_on_silence(self, mock_get_provider):
        # Setup mock LLM provider
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "User transcript: [silence]\nAgent reply: Hello! How can I help?"
        mock_llm.provider_name = "gemini"
        mock_llm.model_name = "gemini-3.5-flash"
        mock_get_provider.return_value = mock_llm

        agent = QWRAgent(
            call_sid="test-sid",
            stream_sid="test-stream-sid",
            call_id="test-id",
            llm=mock_llm,
        )

        # Call chat with empty/silence text
        user_transcript, agent_reply = await agent.chat(user_text="[silence]")

        # Check that it returns empty response and does NOT add to history
        self.assertEqual(user_transcript, "[silence]")
        self.assertEqual(agent_reply, "")
        self.assertEqual(len(agent._history), 0)


