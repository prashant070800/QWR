from unittest import TestCase

from telephony.audio import EXOTEL_CHUNK_BYTES, chunk_duration_seconds, chunk_pcm, generate_tone_pcm


class AudioTests(TestCase):
    def test_generate_tone_pcm_is_10_seconds_of_8khz_16bit_mono_audio(self):
        pcm = generate_tone_pcm(duration_seconds=10.0)

        self.assertEqual(len(pcm), 10 * 8000 * 2)

    def test_chunk_pcm_uses_exotel_chunk_size(self):
        pcm = generate_tone_pcm(duration_seconds=0.2)

        chunks = list(chunk_pcm(pcm))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), EXOTEL_CHUNK_BYTES)

    def test_chunk_duration_matches_sample_rate(self):
        duration = chunk_duration_seconds(b"\x00" * EXOTEL_CHUNK_BYTES, sample_rate=8000)

        self.assertEqual(duration, 0.2)
