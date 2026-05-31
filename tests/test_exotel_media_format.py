from unittest import TestCase

from telephony.consumers import ExotelStreamState, ExotelVoicebotConsumer


class ExotelMediaFormatTests(TestCase):
    def _consumer_with_media_format(self, media_format):
        consumer = ExotelVoicebotConsumer()
        consumer.state = ExotelStreamState(media_format=media_format)
        return consumer

    def test_accepts_exotel_base64_transport_encoding(self):
        consumer = self._consumer_with_media_format(
            {
                "encoding": "base64",
                "sample_rate": "8000",
                "bit_rate": "128kbps",
            }
        )

        consumer._validate_media_format()

        self.assertEqual(consumer.get_sample_rate(), 8000)

    def test_rejects_unknown_encoding(self):
        consumer = self._consumer_with_media_format(
            {
                "encoding": "opus",
                "sample_rate": "8000",
                "bit_rate": "128kbps",
            }
        )

        with self.assertRaisesRegex(ValueError, "Unsupported Exotel media encoding"):
            consumer._validate_media_format()

    def test_rejects_unsupported_sample_rate(self):
        consumer = self._consumer_with_media_format(
            {
                "encoding": "base64",
                "sample_rate": "44100",
                "bit_rate": "705600bps",
            }
        )

        with self.assertRaisesRegex(ValueError, "Unsupported Exotel sample_rate"):
            consumer._validate_media_format()

    def test_rejects_bit_rate_that_does_not_match_pcm_shape(self):
        consumer = self._consumer_with_media_format(
            {
                "encoding": "base64",
                "sample_rate": "8000",
                "bit_rate": "64kbps",
            }
        )

        with self.assertRaisesRegex(ValueError, "Unsupported Exotel bit_rate"):
            consumer._validate_media_format()
