import asyncio
from unittest.mock import AsyncMock, patch
from django.test import SimpleTestCase
from telephony.notifications import dispatch_summary_notification


class NotificationsTests(SimpleTestCase):
    @patch("telephony.notifications.send_telegram_notification", new_callable=AsyncMock)
    @patch("telephony.notifications.mock_deliver_notification", new_callable=AsyncMock)
    @patch("telephony.notifications.settings")
    def test_telegram_configured_and_succeeds(self, mock_settings, mock_deliver, mock_telegram):
        async def run():
            mock_settings.telegram_bot_token = "token123"
            mock_settings.telegram_chat_id = "chat123"
            mock_telegram.return_value = True

            success = await dispatch_summary_notification("Test summary", "+919999999999")
            self.assertTrue(success)
            mock_telegram.assert_called_once()
            mock_deliver.assert_not_called()
        asyncio.run(run())

    @patch("telephony.notifications.send_telegram_notification", new_callable=AsyncMock)
    @patch("telephony.notifications.mock_deliver_notification", new_callable=AsyncMock)
    @patch("telephony.notifications.settings")
    def test_telegram_configured_but_fails_falls_back(self, mock_settings, mock_deliver, mock_telegram):
        async def run():
            mock_settings.telegram_bot_token = "token123"
            mock_settings.telegram_chat_id = "chat123"
            mock_telegram.return_value = False
            mock_deliver.return_value = True

            success = await dispatch_summary_notification("Test summary", "+919999999999")
            self.assertTrue(success)
            mock_telegram.assert_called_once()
            mock_deliver.assert_called_once()
        asyncio.run(run())

    @patch("telephony.notifications.send_telegram_notification", new_callable=AsyncMock)
    @patch("telephony.notifications.mock_deliver_notification", new_callable=AsyncMock)
    @patch("telephony.notifications.settings")
    def test_telegram_not_configured_falls_back(self, mock_settings, mock_deliver, mock_telegram):
        async def run():
            mock_settings.telegram_bot_token = ""
            mock_settings.telegram_chat_id = ""
            mock_deliver.return_value = True

            success = await dispatch_summary_notification("Test summary", "+919999999999")
            self.assertTrue(success)
            mock_telegram.assert_not_called()
            mock_deliver.assert_called_once()
        asyncio.run(run())
