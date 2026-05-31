# QWR AI Voice Bot

Django + Channels backend for the QWR AI Voice Bot assignment. The Exotel AgentStream / Voicebot WebSocket endpoint accepts Exotel call events, speaks a TTS greeting, transcribes caller audio, gets an AI reply, and streams synthesized voice back to the caller.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/daphne -b 0.0.0.0 -p 8000 qwr_voicebot.asgi:application
```

Health check:

```bash
curl http://localhost:8000/health/
```

## Provider Setup

Copy `.env.example` to `.env`, then configure one chat provider:

```bash
# Gemini
AI_PROVIDER=gemini
AI_MODEL=gemini-2.0-flash
GEMINI_API_KEY=...

# ChatGPT / OpenAI
AI_PROVIDER=openai
AI_MODEL=gpt-4o-mini
OPENAI_API_KEY=...

# Anthropic Claude
AI_PROVIDER=anthropic
AI_MODEL=claude-3-5-haiku-20241022
ANTHROPIC_API_KEY=...
```

For local voice testing, `TTS_PROVIDER=gtts` gives audible speech without a cloud key. `STT_PROVIDER=stub` keeps the pipeline working with canned transcripts; use `deepgram` or `google` for real caller transcription.

## Exotel Voicebot Applet

Configure the Voicebot Applet URL as:

```text
wss://<your-public-domain>/ws/exotel/voicebot/
```

For local testing, expose Daphne through a TLS tunnel such as ngrok, Cloudflare Tunnel, or grout. Daphne itself is plain HTTP locally, so point the tunnel at `http://localhost:8000`, not `https://localhost:8000`.

Example with grout:

```bash
grout http://localhost:8000 prashant
```

If grout prints a public route such as `https://prashant.jaxl.io`, configure Exotel with:

```text
wss://prashant.jaxl.io/ws/exotel/voicebot/
```

Exotel sends JSON WebSocket messages and the consumer currently handles:

- `connected`
- `start`
- `media`
- `dtmf`
- `mark`
- `clear`
- `stop`

On `start`, the server synthesizes a greeting and sends little-endian signed 16-bit mono PCM audio, base64 encoded in Exotel `media` frames. The audio uses the `start.media_format.sample_rate` when Exotel provides it, falling back to 8 kHz. Frames are sent in 20 ms chunks and paced according to the negotiated sample rate, then followed by a `mark` event named `qwr-greeting-complete`.

## Current Architecture

- `qwr_voicebot.asgi` wires HTTP and WebSocket traffic.
- `telephony.routing` exposes `/ws/exotel/voicebot/`.
- `telephony.consumers.ExotelVoicebotConsumer` extends `AsyncJsonWebsocketConsumer` and maps each Exotel event to an explicit handler.
- `telephony.audio` contains PCM generation/chunking helpers.

## Next Milestones

The broader assignment roadmap lives in `TASKS.md`. The immediate next engineering step is to replace the generated tone with a voice pipeline:

1. stream inbound Exotel PCM to STT or a realtime voice model,
2. inject the selected QWR conversation mode prompt,
3. stream synthesized response audio back as Exotel `media` frames,
4. persist call metadata and speaker-labeled transcript turns.
