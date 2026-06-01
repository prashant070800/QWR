# QWR AI Voice Bot — Status And Next Steps

## What Already Happened

### Completed Or Mostly Working

- Django + Channels ASGI backend exists.
- `/health/` HTTP health check exists.
- Exotel WebSocket route exists at `/ws/exotel/voicebot/`.
- Exotel consumer accepts `connected`, `start`, `media`, `dtmf`, `mark`, `clear`, and `stop`.
- Exotel `start` captures call IDs, caller/callee numbers, and media format.
- Exotel media format validation is implemented for supported PCM settings.
- Bot can generate a greeting and send base64 PCM media frames back to Exotel.
- Fallback tone works when TTS cannot produce audio.
- Incoming audio is buffered and flushed after silence.
- Per-call `QWRAgent` exists, so history does not leak across calls.
- LLM providers exist for Gemini, OpenAI, and Anthropic.
- STT providers exist for stub, Deepgram, and Google.
- TTS providers exist for gTTS, Google, and stub.
- QWR website context path exists through scraper/vector tooling.
- Barge-in support exists: caller speech can cancel active playback and send Exotel `clear`.
- README documents setup, provider choices, Exotel tunnel setup, architecture, and current limitations.
- Assignment requirements have been extracted into `TASKS.md`.
- A higher-level implementation plan exists in `ASSIGNMENT_PLAN.md`.

### Verified Locally

- `pytest` is not installed in the current virtualenv.
- Built-in unittest suite passes:

```bash
.venv/bin/python -m unittest discover -v
```

Result: 12 tests passed.

Current test coverage includes:

- Audio chunk duration and PCM framing.
- Tone generation.
- Exotel media format validation.
- Barge-in and playback cancellation.
- Stop-state send prevention.

## What Is Still Missing

### Biggest Assignment Gaps

- Supabase persistence is not implemented.
- Calls, profiles, transcript turns, and summaries are not stored.
- Mode selection is not implemented.
- DTMF digits are handled as generic text, not mapped to stateful choices.
- Mode prompt injection is not implemented.
- Known-caller lookup is not implemented.
- Unknown-caller intake and anonymous flow are not implemented.
- Structured extraction for name, company, role, city, reason, and destination is not implemented.
- General web search for current facts is not implemented.
- Source URLs are not stored with turns.
- Summary generation and email/SMS delivery are not implemented.
- Dashboard is not implemented.
- WER test set and WER script are not implemented.
- Latency report is logged but not persisted or summarized.
- Exotel terminal webhook for recording/duration metadata is missing.
- WebSocket authentication validation is missing.
- Final README sections are still incomplete: ER diagram, schema export, WER/latency results, extraction/diarization decisions, final deliverables.

## Next Steps In The Right Order

### Step 1 — Build Supabase Foundation

Goal: make every call and transcript durable.

- Add `supabase/schema.sql`.
- Define `profiles`, `calls`, `transcript_turns`, and `summaries`.
- Add indexes for phone lookup, call status, call timestamp, and transcript full-text search.
- Add service-role/RLS notes in README.
- Add a storage adapter module for creating/updating calls and inserting transcript turns.
- Add local tests with a fake storage backend.

Why first: mode, intake, dashboard, summary, and measurement all depend on stored call data.

### Step 2 — Persist Existing Call Pipeline

Goal: connect the current working Exotel pipeline to storage.

- On `start`, create a `calls` row with provider IDs and caller number.
- On every user/bot turn, insert `transcript_turns`.
- On `stop`/disconnect, update status, duration, and end timestamp.
- Persist per-turn latency for assistant replies.
- Keep logging as fallback, but make Supabase the source of truth.

Done when: one local simulated call produces a call row plus speaker-labeled transcript turns.

### Step 3 — Add Mode Selection

Goal: satisfy the 20% mode-selection rubric item.

- Add mode constants and appendix prompt blocks.
- Add call state for `MODE_SELECTION`.
- Start calls with: Think press/say 1, Challenge 2, Explore 3, Guide 4.
- Map DTMF `1`-`4` to the four modes.
- Parse spoken mode names and number words.
- Persist selected mode to `calls.selected_mode`.
- Inject selected mode prompt into `QWRAgent`.
- Re-prompt on no-input or unrecognized input.

Done when: both keypad and voice can select a mode and the agent prompt actually changes.

### Step 4 — Add Caller Identity And Intake

Goal: satisfy known/unknown caller and profile extraction requirements.

- Normalize caller number to E.164.
- Lookup profile by phone on call start.
- Known caller: greet by name and link call to profile.
- Unknown caller: ask whether to share details or continue anonymously.
- Accept both voice and DTMF for that choice.
- Capture name, company, role, city, reason for calling, and email/SMS destination.
- Extract structured fields using an LLM JSON extraction helper plus conservative validation.
- Leave unknown fields null.
- Personalize later turns with profile context.

Done when: a new caller can create/enrich a profile or continue anonymously.

### Step 5 — Add Summary Generation And Delivery

Goal: satisfy the 10% summary rubric item.

- Detect phrases like “send me a summary” during the call.
- Generate summary from stored transcript, not only memory.
- Store summary text and delivery status.
- Implement one reliable delivery channel first: email if credentials are available, SMS if Exotel/Twilio SMS is easier.
- Generate summary automatically on call end.

Done when: completed calls get a stored summary and a delivered email/SMS sample.

### Step 6 — Add Dashboard

Goal: provide the review UI required by the assignment.

- Add Django dashboard routes/templates.
- Active calls page: in-progress calls.
- History page: completed calls with caller, profile, mode, timestamp, duration.
- Detail page: profile, summary, transcript, latency, recording URL when present.
- Search page/filter using transcript full-text search.

Done when: evaluator can inspect stored calls without touching logs.

### Step 7 — Add Web Search And Source Metadata

Goal: satisfy current factual answers beyond the QWR website.

- Add a search provider abstraction.
- Route QWR-specific questions to `questionwhatsreal.com` context first.
- Add PDF fact-sheet fallback for QWR.
- Route non-QWR current factual questions to web search.
- Store source URLs in transcript turn metadata.
- Document LinkedIn limitations honestly.

Done when: searched answers include source metadata for dashboard/review.

### Step 8 — Add Measurement And Final Deliverables

Goal: make the submission credible.

- Add WER fixture set with Indian-accented English/Hinglish examples.
- Add WER script.
- Add latency report script from stored transcript turns.
- Add Exotel webhook/passthru endpoint for final duration/recording metadata.
- Add WebSocket auth validation.
- Update README with ER diagram, schema, provider rationale, latency, WER, extraction/diarization choices, limitations, and setup.
- Prepare final deliverables: dial-in or recording, dashboard link/screen recording, schema export, sample summary.

Done when: README can be sent as the final assignment handoff.

## Immediate Implementation Sprint

Do these next, in this exact order:

1. Add `supabase/schema.sql`.
2. Add `ai_agent/storage.py` or `telephony/storage.py` with a Supabase adapter and fake test adapter.
3. Wire call lifecycle persistence into `ExotelVoicebotConsumer`.
4. Wire transcript persistence into `_handle_user_speech()` and greeting playback.
5. Add mode constants and prompt injection in `QWRAgent`.
6. Add state-aware mode selection for DTMF and speech.
7. Add tests for mode selection and persisted transcript turns.

This first sprint attacks the biggest blockers: storage plus mode behavior. Once those are in, intake, summary, and dashboard become straightforward instead of floating pieces.
