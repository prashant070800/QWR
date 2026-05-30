# QWR AI Voice Bot

Django + Channels backend for the QWR AI Voice Bot assignment. The first milestone is an Exotel AgentStream / Voicebot WebSocket endpoint that accepts Exotel call events and plays 10 seconds of generated PCM audio back to the caller.

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

On `start`, the server sends 10 seconds of little-endian signed 16-bit mono PCM audio, base64 encoded in Exotel `media` frames. The audio uses the `start.media_format.sample_rate` when Exotel provides it, falling back to 8 kHz. Frames are sent in 3200-byte chunks and paced according to the negotiated sample rate, then followed by a `mark` event named `qwr-demo-music-complete`.

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
