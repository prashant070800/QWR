# QWR AI Voice Bot — Assignment Plan

## Scope Readout

The assignment asks for a callable AI voice bot, not just a chat demo. The graded core is:

- Inbound PSTN call through Exotel/Twilio/Plivo.
- Multi-turn speech pipeline with caller audio, transcription, LLM response, and spoken bot audio.
- Four selectable modes: Think, Challenge, Explore, Guide.
- Dual input for every choice: spoken answer and keypad DTMF.
- Live QWR/company answers grounded in `questionwhatsreal.com`, plus general web search for current facts.
- Supabase-backed profiles, calls, speaker-labeled transcript turns, and summaries.
- Known-caller lookup, unknown-caller intake, anonymous mode, and structured profile extraction.
- Dashboard for active calls, call history, transcript detail, and search.
- Summary generated from stored transcript and delivered by email or SMS.
- README with architecture, ER diagram, provider choices, latency, WER, extraction/diarization decisions, tradeoffs, and deliverables.

Optional but useful: call/network quality detection and adaptive prompts.

## Current Repo State

Already present:

- Django + Channels ASGI project.
- Exotel WebSocket route and event consumer.
- Per-call AI agent with conversation history.
- STT provider abstraction for stub, Deepgram, and Google.
- TTS provider abstraction for gTTS, Google, and stub.
- LLM provider abstraction for Gemini, OpenAI, and Anthropic.
- QWR website fetching/vector context path.
- Audio chunking, media sendback, DTMF event handling, silence-based turn detection, and barge-in support.
- Initial README and detailed `TASKS.md`.

Main gaps:

- No Supabase/Postgres persistence layer yet.
- Mode selection is not implemented as a stateful flow.
- DTMF is currently forwarded as generic text, not mapped to option state.
- Intake/profile matching/extraction is not implemented.
- Transcript turns are logged in memory, not stored.
- Summary generation and delivery are missing.
- Dashboard is missing.
- Web search beyond QWR website data is missing.
- WER and latency measurement artifacts are missing.
- Exotel terminal webhook/recording metadata and WebSocket auth are missing.

## Delivery Strategy

Build the durable data model first, then route the live call through a small state machine. The assignment score depends more on clean integration breadth than UI polish, so prioritize call behavior, storage, and measurable evidence before dashboard refinement.

## Honest Estimate

Minimum demo-ready version: 3 to 4 focused days if provider credentials are available.

Stronger submission with deployed dashboard, WER/latency evidence, recorded call, and polished README: 5 to 7 focused days.

External access needed:

- Exotel number/AgentStream access and call credits.
- Supabase project URL plus service-role key.
- At least one production STT/TTS/LLM key combination.
- Email or SMS delivery provider credentials.

## Critical Path

1. Supabase schema and repository layer.
2. Persist calls and transcript turns from the existing Exotel pipeline.
3. Add a call state machine for mode selection, known/unknown caller handling, intake, confirmations, summary requests, and free conversation.
4. Add mode prompt injection and DTMF mapping.
5. Add structured extraction for profile fields.
6. Add summary generation and email/SMS delivery.
7. Build minimal dashboard against stored data.
8. Add measurement scripts and final README/deliverable artifacts.

## Phase Plan

### Phase A — Data Foundation

- Create `supabase/schema.sql` with `profiles`, `calls`, `transcript_turns`, and `summaries`.
- Include indexes for phone lookup, call status, timestamps, and transcript full-text search.
- Add RLS notes and document that backend writes use the service-role key.
- Add a Python storage adapter with no-op/local fallback for tests.
- Store call start/update/end lifecycle records from `ExotelVoicebotConsumer`.
- Store every caller and bot turn with sequence number, speaker, text, latency, source metadata, and timestamps.

Done when: a local/unit test can create a profile, call, transcript turns, and summary through the storage adapter.

### Phase B — Call Flow State Machine

- Add explicit call states: `GREETING`, `MODE_SELECTION`, `IDENTITY_CHECK`, `UNKNOWN_CALLER_CHOICE`, `INTAKE`, `CONVERSATION`, `SUMMARY_CONFIRM`, `ENDED`.
- Convert DTMF digits based on current state instead of sending `User pressed key X` to the LLM.
- Implement universal option handling with spoken labels and keypad mappings.
- Add graceful no-input and unrecognized-input retry behavior.
- Persist selected mode to the call record.

Done when: tests prove mode selection works by both speech and DTMF, including retry/fallback.

### Phase C — Mode Prompts

- Add mode prompt constants for Think, Challenge, Explore, and Guide from the appendix.
- Let `QWRAgent` accept and update selected mode.
- Inject the selected mode block into the system prompt for all later LLM calls.
- Add tests or fixture checks that each selected mode changes the prompt.

Done when: a call can select each mode and subsequent replies use the correct behavioral prompt.

### Phase D — Identity And Intake

- Normalize caller phone numbers to E.164.
- Match profiles by phone number on call start.
- For known callers, greet by name and link the call.
- For unknown callers, ask whether to share details or stay anonymous using voice/DTMF.
- Capture name, company, role, city, reason for calling, and email/phone delivery destination.
- Use a hybrid extraction approach: scripted prompts for required moments plus LLM structured JSON extraction from natural speech.
- Validate extracted fields and leave unknown fields null.

Done when: unknown callers can create/enrich a profile, or continue anonymously, and the call record is linked correctly.

### Phase E — Search And QWR Grounding

- Keep QWR website as the primary source for QWR-specific questions.
- Add a general web search provider abstraction for current factual questions.
- Store source URLs in turn metadata for searched answers.
- Add QWR fact-sheet fallback from the PDF for website failures.
- Document LinkedIn limitations without scraping.

Done when: QWR questions use website/fallback context and non-QWR current questions can call search.

### Phase F — Summary Delivery

- Detect summary requests during the call.
- Generate end-of-call summary from stored transcript.
- Store summary text, delivery destination, delivery channel, and delivery status.
- Implement one reliable channel first, preferably email unless SMS credentials are already available.
- Trigger summary generation on call end.

Done when: a completed call produces a persisted summary and a delivered email/SMS or a recorded provider response.

### Phase G — Dashboard

- Build minimal Django dashboard views, not in the call path.
- Active calls: show in-progress calls.
- History: show completed calls with caller/profile, mode, time, duration, status.
- Detail: show profile, selected mode, summary, transcript turns, latency, recording URL when present.
- Search: query transcript full-text index.

Done when: evaluator can inspect call history and transcript details from stored Supabase data.

### Phase H — Measurement And Deliverables

- Add WER test set with Indian-accented English/Hinglish references.
- Add WER script and report result in README.
- Add latency benchmark/report from real or recorded call logs.
- Add Exotel terminal webhook for recording/duration metadata.
- Add WebSocket auth validation.
- Update README with architecture diagram/ER diagram, setup, provider choices, extraction/diarization decisions, limitations, and final deliverable links.
- Prepare recorded call or live dial-in instructions, dashboard link/screen recording, schema export, and sample summary.

Done when: README can stand alone as the assignment submission guide.

## Recommended First Implementation Slice

Start with persistence plus mode selection. This unlocks the biggest rubric items and gives the rest of the work a stable base.

1. Add schema and storage adapter.
2. Persist call lifecycle and transcript turns.
3. Implement mode constants and prompt injection.
4. Add state-aware DTMF/spoken mode selection.
5. Add tests for mode selection and transcript persistence.

After that, move to profile intake and summary delivery before spending time on dashboard polish.
