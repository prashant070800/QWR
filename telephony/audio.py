"""Small PCM helpers for Exotel bidirectional media streams."""

from __future__ import annotations

import audioop
import base64
import math
import struct
import wave
from collections.abc import Iterable
from pathlib import Path


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


def load_wav_pcm(
    wav_path: str | Path,
    target_sample_rate: int = EXOTEL_SAMPLE_RATE_HZ,
) -> bytes:
    """Read *wav_path* and return little-endian signed 16-bit mono PCM.

    The function handles:
    - multi-channel → mono downmix (via audioop.tomono)
    - sample-rate conversion (via audioop.ratecv)
    - sample-width normalisation to 16-bit (via audioop.lin2lin)
    """
    with wave.open(str(wav_path), "rb") as wf:
        src_channels = wf.getnchannels()
        src_sample_width = wf.getsampwidth()   # bytes per sample
        src_sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    # 1. Normalise width to 2 bytes (16-bit)
    if src_sample_width != 2:
        raw = audioop.lin2lin(raw, src_sample_width, 2)
        src_sample_width = 2

    # 2. Downmix to mono
    if src_channels > 1:
        raw = audioop.tomono(raw, src_sample_width, 0.5, 0.5)
        src_channels = 1

    # 3. Resample to target rate if necessary
    if src_sample_rate != target_sample_rate:
        raw, _ = audioop.ratecv(
            raw,
            src_sample_width,
            src_channels,
            src_sample_rate,
            target_sample_rate,
            None,
        )

    return raw
