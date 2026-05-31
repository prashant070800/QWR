"""Speech-to-Text module for the QWR Voice Bot.

Supports:
- "stub"   — returns a canned response (for development without API keys)
- "google" — Google Cloud Speech-to-Text REST API
- "deepgram" — Deepgram Nova-2 REST API

The STT provider is configured via STT_PROVIDER env var.

Usage
-----
    from ai_agent.stt import transcribe_audio
    transcript = await transcribe_audio(pcm_bytes, sample_rate=8000)
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from ai_agent.config import settings

logger = logging.getLogger(__name__)


async def transcribe_audio(
    pcm_bytes: bytes,
    sample_rate: int = 8000,
    call_sid: str = "unknown",
    stream_sid: str = "unknown",
) -> str:
    """Transcribe raw PCM audio bytes to text.

    Parameters
    ----------
    pcm_bytes:
        Little-endian signed 16-bit mono PCM audio.
    sample_rate:
        Sample rate in Hz (Exotel default is 8000).
    call_sid / stream_sid:
        For structured log output only.

    Returns
    -------
    str
        Transcribed text, or empty string if nothing was detected.
    """
    log_prefix = f"call_sid={call_sid} stream_sid={stream_sid}"
    provider = settings.stt_provider.lower()

    logger.info(
        "%s STT request provider=%s pcm_bytes=%d sample_rate=%d",
        log_prefix,
        provider,
        len(pcm_bytes),
        sample_rate,
    )

    if provider == "stub":
        return await _stub_transcribe(pcm_bytes, log_prefix)

    if provider == "google":
        return await _google_transcribe(pcm_bytes, sample_rate, log_prefix)

    if provider == "deepgram":
        return await _deepgram_transcribe(pcm_bytes, sample_rate, log_prefix)

    logger.warning("%s Unknown STT provider=%r, falling back to stub", log_prefix, provider)
    return await _stub_transcribe(pcm_bytes, log_prefix)


# ---------------------------------------------------------------------------
# Stub (development / testing)
# ---------------------------------------------------------------------------

async def _stub_transcribe(pcm_bytes: bytes, log_prefix: str) -> str:
    """Return a fixed transcript — useful for testing without API keys."""
    stub_text = "What products does QWR make?"
    logger.info(
        "%s STT stub returning canned transcript=%r pcm_bytes=%d",
        log_prefix,
        stub_text,
        len(pcm_bytes),
    )
    return stub_text


# ---------------------------------------------------------------------------
# Google Cloud Speech-to-Text
# ---------------------------------------------------------------------------

async def _google_transcribe(
    pcm_bytes: bytes,
    sample_rate: int,
    log_prefix: str,
) -> str:
    """Transcribe using Google Cloud Speech-to-Text REST API."""
    import asyncio
    import json
    import os

    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("httpx is required for Google STT. pip install httpx") from exc

    credentials_path = settings.google_credentials_path
    if not credentials_path or not os.path.exists(credentials_path):
        logger.error(
            "%s GOOGLE_APPLICATION_CREDENTIALS not set or file not found. "
            "Falling back to stub STT.",
            log_prefix,
        )
        return await _stub_transcribe(pcm_bytes, log_prefix)

    # Get access token using service account credentials
    def _get_token() -> str:
        import google.auth  # type: ignore[import-untyped]
        import google.auth.transport.requests  # type: ignore[import-untyped]

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        req = google.auth.transport.requests.Request()
        creds.refresh(req)
        return creds.token  # type: ignore[return-value]

    loop = asyncio.get_event_loop()
    try:
        token = await loop.run_in_executor(None, _get_token)
    except Exception as exc:
        logger.error("%s Failed to get Google auth token: %s", log_prefix, exc)
        return ""

    audio_b64 = base64.b64encode(pcm_bytes).decode("ascii")

    payload = {
        "config": {
            "encoding": "LINEAR16",
            "sampleRateHertz": sample_rate,
            "languageCode": "en-IN",
            "alternativeLanguageCodes": ["hi-IN"],
            "model": "phone_call",
            "useEnhanced": True,
        },
        "audio": {"content": audio_b64},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://speech.googleapis.com/v1/speech:recognize",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.status_code != 200:
        logger.error(
            "%s Google STT HTTP error status=%d body=%s",
            log_prefix,
            resp.status_code,
            resp.text[:200],
        )
        return ""

    data = resp.json()
    results = data.get("results", [])
    if not results:
        logger.info("%s Google STT returned no results (silence or noise)", log_prefix)
        return ""

    transcript = results[0]["alternatives"][0]["transcript"].strip()
    confidence = results[0]["alternatives"][0].get("confidence", 0)

    logger.info(
        "%s Google STT transcript=%r confidence=%.2f",
        log_prefix,
        transcript,
        confidence,
    )
    return transcript


# ---------------------------------------------------------------------------
# Deepgram
# ---------------------------------------------------------------------------

async def _deepgram_transcribe(
    pcm_bytes: bytes,
    sample_rate: int,
    log_prefix: str,
) -> str:
    """Transcribe using Deepgram Nova-2 REST API."""
    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("httpx is required for Deepgram STT. pip install httpx") from exc

    api_key = settings.deepgram_api_key
    if not api_key:
        logger.error(
            "%s DEEPGRAM_API_KEY not set. Falling back to stub STT.",
            log_prefix,
        )
        return await _stub_transcribe(pcm_bytes, log_prefix)

    url = (
        f"https://api.deepgram.com/v1/listen"
        f"?model=nova-2-phonecall"
        f"&encoding=linear16"
        f"&sample_rate={sample_rate}"
        f"&language=en-IN"
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            url,
            content=pcm_bytes,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "audio/raw",
            },
        )

    if resp.status_code != 200:
        logger.error(
            "%s Deepgram STT HTTP error status=%d body=%s",
            log_prefix,
            resp.status_code,
            resp.text[:200],
        )
        return ""

    data = resp.json()
    try:
        transcript = (
            data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        )
        confidence = data["results"]["channels"][0]["alternatives"][0].get("confidence", 0)
    except (KeyError, IndexError):
        logger.info("%s Deepgram returned no transcript (silence?)", log_prefix)
        return ""

    logger.info(
        "%s Deepgram STT transcript=%r confidence=%.2f",
        log_prefix,
        transcript,
        confidence,
    )
    return transcript
