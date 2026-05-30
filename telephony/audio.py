"""Small PCM helpers for Exotel bidirectional media streams."""

from __future__ import annotations

import base64
import math
import struct
from collections.abc import Iterable


EXOTEL_SAMPLE_RATE_HZ = 8000
EXOTEL_SAMPLE_WIDTH_BYTES = 2
EXOTEL_CHANNELS = 1
EXOTEL_CHUNK_BYTES = 3200


def generate_tone_pcm(
    duration_seconds: float = 10.0,
    sample_rate: int = EXOTEL_SAMPLE_RATE_HZ,
    frequency_hz: float = 440.0,
    amplitude: float = 0.18,
) -> bytes:
    """Generate little-endian signed 16-bit mono PCM."""

    total_samples = int(duration_seconds * sample_rate)
    clipped_amplitude = max(0.0, min(amplitude, 1.0))
    max_value = int(32767 * clipped_amplitude)

    frames = bytearray()
    for index in range(total_samples):
        sample = int(max_value * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    return bytes(frames)


def chunk_pcm(pcm: bytes, chunk_size: int = EXOTEL_CHUNK_BYTES) -> Iterable[bytes]:
    """Yield Exotel-friendly chunks, padding the final frame if needed."""

    for offset in range(0, len(pcm), chunk_size):
        chunk = pcm[offset : offset + chunk_size]
        if len(chunk) < chunk_size:
            chunk = chunk + b"\x00" * (chunk_size - len(chunk))
        yield chunk


def b64_audio(pcm_chunk: bytes) -> str:
    return base64.b64encode(pcm_chunk).decode("ascii")


def chunk_duration_seconds(
    chunk: bytes,
    sample_rate: int = EXOTEL_SAMPLE_RATE_HZ,
    sample_width_bytes: int = EXOTEL_SAMPLE_WIDTH_BYTES,
    channels: int = EXOTEL_CHANNELS,
) -> float:
    bytes_per_second = sample_rate * sample_width_bytes * channels
    return len(chunk) / bytes_per_second
