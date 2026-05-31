"""Text-to-Speech module for the QWR Voice Bot.

Supports:
- "gtts"   — Google Translate TTS (FREE, no API key needed — recommended for dev)
- "stub"   — returns silent PCM (for testing without internet)
- "google" — Google Cloud Text-to-Speech API (production)

Set TTS_PROVIDER in your .env file.

Usage
-----
    from ai_agent.tts import synthesize_speech
    pcm_bytes = await synthesize_speech("Hello, welcome to QWR!", sample_rate=8000)
"""

from __future__ import annotations

import audioop
import base64
import io
import logging
import struct
import wave

from ai_agent.config import settings

logger = logging.getLogger(__name__)


async def synthesize_speech(
    text: str,
    sample_rate: int = 8000,
    call_sid: str = "unknown",
    stream_sid: str = "unknown",
) -> bytes:
    """Convert *text* to raw 16-bit mono PCM audio bytes.

    Parameters
    ----------
    text:
        The text to speak aloud.
    sample_rate:
        Target sample rate in Hz (Exotel default 8000).
    call_sid / stream_sid:
        Used for structured log output only.

    Returns
    -------
    bytes
        Little-endian signed 16-bit mono PCM audio, ready to chunk and
        send to Exotel as base64 media frames.
    """
    log_prefix = f"call_sid={call_sid} stream_sid={stream_sid}"
    provider = settings.tts_provider.lower()

    logger.info(
        "%s TTS request provider=%s text_len=%d preview=%r",
        log_prefix,
        provider,
        len(text),
        text[:80],
    )

    if provider == "gtts":
        pcm = await _gtts_synthesize(text, sample_rate, log_prefix)
        if pcm:
            return pcm
        logger.warning("%s gTTS failed, falling back to stub", log_prefix)
        return _stub_synthesize(text, sample_rate, log_prefix)

    if provider == "stub":
        return _stub_synthesize(text, sample_rate, log_prefix)

    if provider == "google":
        pcm = await _google_synthesize(text, sample_rate, log_prefix)
        if pcm:
            return pcm
        logger.warning("%s Google TTS failed, falling back to gtts", log_prefix)
        return await _gtts_synthesize(text, sample_rate, log_prefix)

    logger.warning(
        "%s Unknown TTS provider=%r, falling back to gtts", log_prefix, provider
    )
    return await _gtts_synthesize(text, sample_rate, log_prefix)


# ---------------------------------------------------------------------------
# gTTS — Google Translate TTS (FREE, no API key)
# ---------------------------------------------------------------------------

async def _gtts_synthesize(text: str, sample_rate: int, log_prefix: str) -> bytes:
    """Use gTTS (Google Translate TTS, free) to synthesize speech.

    gTTS returns an MP3. We convert it to 16-bit mono PCM via pydub or
    a fallback using audioop if pydub is not installed.
    """
    import asyncio

    def _sync_gtts() -> bytes:
        try:
            from gtts import gTTS  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "gtts is not installed. Run: pip install gtts"
            ) from exc

        # Synthesize to MP3 in memory
        tts = gTTS(text=text, lang="en", tld="co.in", slow=False)
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_buf.seek(0)
        mp3_bytes = mp3_buf.read()

        logger.debug(
            "%s gTTS MP3 size=%d bytes",
            log_prefix,
            len(mp3_bytes),
        )

        # Convert MP3 → PCM using pydub (preferred)
        try:
            from pydub import AudioSegment  # type: ignore[import-untyped]

            audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
            audio = audio.set_channels(1).set_frame_rate(sample_rate).set_sample_width(2)
            pcm = audio.raw_data
            logger.info(
                "%s gTTS synthesized via pydub pcm_bytes=%d",
                log_prefix,
                len(pcm),
            )
            return pcm

        except ImportError:
            pass

        # Fallback: use ffmpeg via subprocess
        try:
            import subprocess
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(mp3_bytes)
                mp3_path = f.name

            wav_path = mp3_path.replace(".mp3", ".wav")
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", mp3_path,
                        "-ar", str(sample_rate),
                        "-ac", "1",
                        "-f", "s16le",
                        wav_path,
                    ],
                    check=True,
                    capture_output=True,
                )
                with open(wav_path, "rb") as f:
                    pcm = f.read()
                logger.info(
                    "%s gTTS synthesized via ffmpeg pcm_bytes=%d",
                    log_prefix,
                    len(pcm),
                )
                return pcm
            finally:
                for p in (mp3_path, wav_path):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.warning("%s ffmpeg not available: %s", log_prefix, exc)

        # Last resort: return empty (caller will fall back to stub)
        logger.error(
            "%s gTTS: neither pydub nor ffmpeg available — cannot convert MP3 to PCM. "
            "Install pydub: pip install pydub",
            log_prefix,
        )
        return b""

    loop = asyncio.get_event_loop()
    pcm = await loop.run_in_executor(None, _sync_gtts)
    return pcm


# ---------------------------------------------------------------------------
# Stub (silence — development / testing without internet)
# ---------------------------------------------------------------------------

def _stub_synthesize(text: str, sample_rate: int, log_prefix: str) -> bytes:
    """Return 2 seconds of silence as 16-bit mono PCM.

    In production use gtts or google TTS provider.
    """
    duration_seconds = 2.0
    num_samples = int(duration_seconds * sample_rate)
    pcm = struct.pack(f"<{num_samples}h", *([0] * num_samples))
    logger.info(
        "%s TTS stub — returning %d samples of silence (text was: %r)",
        log_prefix,
        num_samples,
        text[:80],
    )
    return pcm


# ---------------------------------------------------------------------------
# Google Cloud Text-to-Speech (production)
# ---------------------------------------------------------------------------

async def _google_synthesize(
    text: str,
    sample_rate: int,
    log_prefix: str,
) -> bytes:
    """Synthesize speech using Google Cloud TTS REST API and return raw PCM."""
    import asyncio
    import os

    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("httpx is required. pip install httpx") from exc

    credentials_path = settings.google_credentials_path
    if not credentials_path or not os.path.exists(credentials_path):
        logger.error(
            "%s GOOGLE_APPLICATION_CREDENTIALS not set. Cannot use Google TTS.",
            log_prefix,
        )
        return b""

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
        return b""

    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": settings.tts_language_code,
            "name": settings.tts_voice_name,
        },
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": sample_rate,
            "speakingRate": 0.95,
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.status_code != 200:
        logger.error(
            "%s Google TTS HTTP error status=%d body=%s",
            log_prefix,
            resp.status_code,
            resp.text[:200],
        )
        return b""

    data = resp.json()
    audio_b64 = data.get("audioContent", "")
    if not audio_b64:
        return b""

    audio_bytes = base64.b64decode(audio_b64)
    # Strip 44-byte WAV header to get raw PCM
    pcm = audio_bytes[44:] if audio_bytes[:4] == b"RIFF" else audio_bytes

    logger.info(
        "%s Google TTS synthesized pcm_bytes=%d voice=%s",
        log_prefix,
        len(pcm),
        settings.tts_voice_name,
    )
    return pcm
