import asyncio
import time
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from ai_agent.agent import QWRAgent
from ai_agent.tools.qwr_scraper import QWRScraper

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

    async def test_scraper_fetches_pages_in_parallel(self):
        scraper = QWRScraper()
        
        # Mock _get_page to introduce a sleep delay
        async def mock_get_page(url):
            await asyncio.sleep(0.1)
            return f"Content of {url}"
            
        with patch.object(scraper, "_get_page", side_effect=mock_get_page):
            t0 = time.monotonic()
            context = await scraper.get_context("Help me with home and about info")
            duration = time.monotonic() - t0
            
            # If sequential, fetching 2 pages (home and about) would take >= 0.2s.
            # If parallel, it should take ~0.1s (< 0.18s to allow for scheduling overhead).
            self.assertLess(duration, 0.18)
            self.assertIn("Source: https://questionwhatsreal.com/", context)
            self.assertIn("Source: https://questionwhatsreal.com/about", context)
