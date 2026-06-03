import asyncio
from unittest.mock import AsyncMock, patch
from django.test import TransactionTestCase
from telephony.models import Call, TranscriptTurn, Summary

class SummarySignalTests(TransactionTestCase):
    @patch("telephony.signals.run_in_background")
    @patch("ai_agent.agent.QWRAgent.generate_summary", new_callable=AsyncMock)
    @patch("telephony.signals.mock_deliver_notification", new_callable=AsyncMock)
    def test_summary_generation_signal_flow(self, mock_deliver, mock_gen_summary, mock_run_bg):
        # Setup mocks
        mock_gen_summary.return_value = "Mocked call summary text."
        mock_deliver.return_value = True
        
        # Override background runner to execute immediately in the main test thread
        mock_run_bg.side_effect = lambda target, *args, **kwargs: target(*args, **kwargs)

        # 1. Create a Call
        call = Call.objects.create(
            call_sid="signal-call-123",
            stream_sid="signal-stream-123",
            from_number="+919876543210",
            to_number="+911234567890",
            direction="incoming",
            status="initiated",
        )

        # 2. Add transcript turns
        TranscriptTurn.objects.create(
            call=call,
            seq_number=1,
            speaker="user",
            text="Hello, I need help with my account."
        )
        TranscriptTurn.objects.create(
            call=call,
            seq_number=2,
            speaker="assistant",
            text="Sure, I can help you with that."
        )

        # 3. Mark the call as completed (triggers post_save signal)
        call.status = "completed"
        call.save()

        # Verify mocks were called
        mock_gen_summary.assert_called_once()
        mock_deliver.assert_called_once_with(
            summary_text="Mocked call summary text.",
            phone="+919876543210",
            email=None
        )

        # Check DB records
        summary = Summary.objects.get(call=call)
        self.assertEqual(summary.summary_text, "Mocked call summary text.")
        self.assertEqual(summary.delivery_status, "sent")
        self.assertEqual(summary.destination, "+919876543210")
