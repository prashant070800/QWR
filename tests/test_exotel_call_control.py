import asyncio
from unittest import IsolatedAsyncioTestCase

from telephony.audio import generate_tone_pcm
from telephony.consumers import (
    BARGE_IN_SPEECH_CHUNKS,
    ExotelStreamState,
    ExotelVoicebotConsumer,
)


class RecordingExotelConsumer(ExotelVoicebotConsumer):
    def __init__(self):
        super().__init__()
        self.sent_messages = []

    async def send_json(self, content, close=False):
        self.sent_messages.append(content)


class ExotelCallControlTests(IsolatedAsyncioTestCase):
    def _consumer(self):
        consumer = RecordingExotelConsumer()
        consumer.state = ExotelStreamState(
            stream_sid="stream-123",
            call_sid="call-123",
            media_format={
                "encoding": "base64",
                "sample_rate": "8000",
                "bit_rate": "128kbps",
            },
        )
        consumer.playback_task = None
        consumer.ai_task = None
        consumer.agent = None
        return consumer

    async def test_stream_does_not_send_media_after_call_is_stopped(self):
        consumer = self._consumer()
        consumer.state.is_stopped = True

        await consumer._stream_pcm_to_exotel(generate_tone_pcm(duration_seconds=0.02))

        self.assertEqual(consumer.sent_messages, [])

    async def test_stream_sends_minimal_exotel_media_frame_shape(self):
        consumer = self._consumer()

        await consumer._stream_pcm_to_exotel(generate_tone_pcm(duration_seconds=0.02))

        media_message = consumer.sent_messages[0]
        self.assertEqual(media_message["event"], "media")
        self.assertEqual(media_message["stream_sid"], "stream-123")
        self.assertEqual(set(media_message["media"]), {"payload"})
        self.assertNotIn("sequence_number", media_message)

    async def test_cancel_playback_for_barge_in_cancels_active_playback_task(self):
        consumer = self._consumer()
        consumer.playback_task = asyncio.create_task(asyncio.sleep(60))
        consumer.state.is_playing = True
        consumer.state.speech_chunk_count = BARGE_IN_SPEECH_CHUNKS

        consumer._cancel_playback_for_barge_in()
        await asyncio.sleep(0)

        self.assertTrue(consumer.playback_task.cancelled())
        self.assertFalse(consumer.state.is_playing)
        self.assertTrue(consumer.state.playback_cancel_requested)
        self.assertEqual(consumer.sent_messages[-1]["event"], "clear")

    async def test_cancel_playback_for_barge_in_cancels_active_ai_reply_stream(self):
        consumer = self._consumer()
        consumer.state.is_playing = True
        consumer.state.speech_chunk_count = BARGE_IN_SPEECH_CHUNKS
        consumer.ai_task = asyncio.create_task(asyncio.sleep(60))

        consumer._cancel_playback_for_barge_in()
        await asyncio.sleep(0)

        self.assertTrue(consumer.ai_task.cancelled())
        self.assertFalse(consumer.state.is_playing)
        self.assertTrue(consumer.state.playback_cancel_requested)
        self.assertEqual(consumer.sent_messages[-1]["event"], "clear")

    async def test_barge_in_ignores_short_noise_during_greeting(self):
        consumer = self._consumer()
        consumer.playback_task = asyncio.create_task(asyncio.sleep(60))
        consumer.state.is_playing = True
        consumer.state.speech_chunk_count = BARGE_IN_SPEECH_CHUNKS - 1

        consumer._cancel_playback_for_barge_in()
        await asyncio.sleep(0)

        self.assertFalse(consumer.playback_task.cancelled())
        consumer.playback_task.cancel()
