# QWR AI Voice Bot

Django + Channels backend for the QWR AI Voice Bot assignment. The Exotel AgentStream / Voicebot WebSocket endpoint accepts live call events, speaks a TTS greeting, transcribes caller audio, gets a QWR-aware AI reply, and streams synthesized voice back to the caller.

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

Voice provider options:

- `STT_PROVIDER=stub` returns a canned transcript for local development.
- `STT_PROVIDER=deepgram` sends raw linear16 phone audio to Deepgram Nova-2 phonecall.
- `STT_PROVIDER=google` sends linear16 audio to Google Cloud Speech-to-Text.
- `TTS_PROVIDER=gtts` creates audible speech through gTTS, then converts MP3 to Exotel-ready PCM.
- `TTS_PROVIDER=google` uses Google Cloud Text-to-Speech with the configured language and voice.
- `TTS_PROVIDER=stub` returns silence for tests; the greeting path falls back to a generated tone so callers still hear something.

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

On `start`, the server captures stream metadata, validates Exotel media format, creates a per-call `QWRAgent`, asks the agent to generate the opening greeting, and sends little-endian signed 16-bit mono PCM audio base64 encoded in Exotel `media` frames. The audio uses `start.media_format.sample_rate` when Exotel provides it, falling back to 8 kHz. Frames are sent in 20 ms chunks, paced according to the negotiated sample rate, and followed by a `mark` event named `qwr-greeting-complete`.

## How the Telephony AI Agent Works

The live call path is implemented in `telephony.consumers.ExotelVoicebotConsumer`.

1. Exotel opens a WebSocket at `/ws/exotel/voicebot/`; Django Channels accepts it through `qwr_voicebot.asgi` and `telephony.routing`.
2. Exotel sends `connected`, then `start`; the consumer stores `stream_sid`, `call_sid`, caller/callee numbers, and media format.
3. The consumer validates the media format. Supported audio is raw signed linear PCM, mono, 16-bit, at 8 kHz, 16 kHz, or 24 kHz.
4. A new `QWRAgent` is created for that call only, so conversation history does not leak between calls.
5. The AI agent generates a short natural opening greeting, then the bot speaks it through the configured TTS provider. If TTS fails, the consumer falls back to a generated tone.
6. Exotel `media` events arrive with base64 audio. The consumer decodes each chunk into PCM, appends it to the current audio buffer, and tracks silence/speech chunks.
7. When enough silence is detected after speech (`STT_SILENCE_CHUNKS`, default `10`) and at least one second of audio is buffered, the buffer is flushed to STT.
8. STT returns text. In development the stub returns `What products does QWR make?`; in real calls Deepgram or Google returns the caller transcript.
9. The transcript is passed to `QWRAgent.chat()`. The agent builds a prompt from the QWR system instructions plus recent call history, and sends it to Gemini, OpenAI, or Anthropic depending on `AI_PROVIDER`.
10. The agent reply is synthesized to PCM with gTTS or Google TTS.
11. The PCM is chunked into Exotel-sized frames, base64 encoded, streamed back as `media` events, and closed with a `mark` named `qwr-reply-complete`.
12. On `stop` or WebSocket disconnect, playback/tasks are cancelled and the call transcript plus runtime summary is written to logs.

DTMF input is also supported. When Exotel sends a keypad digit, the consumer records it and routes it into the same AI pipeline as a text override such as `User pressed key 1 on keypad`.

Barge-in is supported for greeting and reply playback. If enough non-silent caller speech chunks are detected while playback is active, the consumer cancels local playback and sends Exotel a `clear` event so queued outbound audio stops while the caller talks.

## Current Architecture

- `qwr_voicebot.asgi` wires HTTP and WebSocket traffic.
- `telephony.routing` exposes `/ws/exotel/voicebot/`.
- `telephony.consumers.ExotelVoicebotConsumer` extends `AsyncJsonWebsocketConsumer` and maps each Exotel event to an explicit handler.
- `telephony.audio` contains PCM generation, loading, conversion, base64, and chunking helpers.
- `ai_agent.agent.QWRAgent` manages per-call conversation memory and QWR system instructions.
- `ai_agent.stt` abstracts stub, Deepgram, and Google Speech-to-Text providers.
- `ai_agent.tts` abstracts gTTS, Google Cloud Text-to-Speech, and test silence generation.
- `ai_agent.providers` abstracts Gemini, OpenAI, and Anthropic chat providers.


## Current Limitations

The broader assignment roadmap lives in `TASKS.md`. The core call loop works, but these pieces are still pending or partial:

- Call/profile/transcript persistence is not yet written to Supabase/Postgres.
- Mode selection for Think, Challenge, Explore, and Guide is not yet implemented.
- No Exotel webhook/passthru endpoint is present yet for recording and terminal metadata.
- STT is turn-based after silence, not true realtime partial transcription.
- TTS replies are generated after full LLM text completion, not streamed token-by-token.
- Dashboard, summaries, delivery, WER reports, and measured latency reports are still roadmap items.
