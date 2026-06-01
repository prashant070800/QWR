# QWR AI Voice Bot — Task List

## Legend
- [ ] = not started | [~] = in progress | [x] = done
- 🔴 CORE = graded, required | 🟡 OPTIONAL = bonus | 🔵 INFRA = setup/scaffolding

## Phase 1: Project Setup & Infra 🔵
- [x] 🔵 Create Django project with Channels ASGI support. (S)
  *Acceptance: `qwr_voicebot.asgi` routes HTTP and WebSocket traffic.*
- [x] 🔵 Add dependency manifest for Django, Channels, and Daphne. (S)
  *Acceptance: `requirements.txt` installs the baseline backend stack.*
- [x] 🔵 Add health-check endpoint. (S)
  *Acceptance: `GET /health/` returns JSON status.*
- [x] 🔵 Add Exotel WebSocket route. (S)
  *Acceptance: `/ws/exotel/voicebot/` resolves to an async consumer.*
- [x] 🔵 Add environment-based settings for secrets, hosts, and debug. (S)
  *Acceptance: local and deployed settings are driven by environment variables.*
- [x] 🔵 Add structured logging with call and stream identifiers. (S)
  *Acceptance: every call-path log includes `call_sid` or `stream_sid` when available.*
- [x] 🔵 Add deployment entrypoint for ASGI server. (S)
  *Acceptance: README documents the exact Daphne/Uvicorn command.*
- [ ] 🔵 Add CI checks for formatting, linting, tests, and Django checks. (M)
  *Acceptance: one command runs all repo quality gates.*

## Phase 2: Supabase Schema 🔴
- [ ] 🔴 Design `profiles` table. (M) [rubric: 15%]
  *Acceptance: table stores phone, name, company, role, city, email, and timestamps.*
- [ ] 🔴 Design `calls` table. (M) [rubric: 15%]
  *Acceptance: table stores provider IDs, caller number, selected mode, duration, status, and profile link.*
- [ ] 🔴 Design `transcript_turns` table. (M) [rubric: 15%]
  *Acceptance: table stores ordered speaker-labeled turns with timing and latency metadata.*
- [ ] 🔴 Design `summaries` table or call summary columns. (S) [rubric: 10%]
  *Acceptance: generated summaries and delivery status can be persisted.*
- [ ] 🔴 Add SQL schema export. (S)
  *Acceptance: `supabase/schema.sql` recreates required tables and indexes.*
- [ ] 🔴 Add Postgres full-text search index for transcripts. (M) [rubric: 5%]
  *Acceptance: dashboard search can query transcript content efficiently.*
- [ ] 🔴 Define row-level security and service-role usage. (M)
  *Acceptance: README states which operations use server credentials and why.*

## Phase 3: Telephony Integration 🔴
- [x] 🔴 Choose Exotel as telephony provider and document the choice. (S)
  *Acceptance: README contains Exotel applet setup details.*
- [x] 🔴 Implement `AsyncJsonWebsocketConsumer` for Exotel. (M)
  *Acceptance: consumer defines connect, disconnect, send_json, receive_json, and event handlers.*
- [x] 🔴 Handle Exotel `connected` and `start` events. (S)
  *Acceptance: stream and call metadata are captured from the start payload.*
- [x] 🔴 Send demo audio back to Exotel. (M)
  *Acceptance: start event triggers base64 PCM media frames for the greeting, with tone fallback if TTS fails.*
- [x] 🔴 Handle Exotel `media`, `dtmf`, `mark`, `clear`, and `stop` events. (M)
  *Acceptance: each supported event maps to a dedicated method.*
- [ ] 🔴 Add Exotel webhook/passthru endpoint for recording and terminal metadata. (M)
  *Acceptance: stream completion metadata can update the call record.*
- [ ] 🔴 Add authentication validation for Exotel WebSocket access. (M)
  *Acceptance: unauthorized WebSocket attempts are rejected or ignored safely.*
- [x] 🔴 Add public tunnel/deployment instructions for Exotel testing. (S)
  *Acceptance: README shows how to expose local Daphne over `wss://`.*
- [ ] 🔴 Run an end-to-end Exotel test call. (L)
  *Acceptance: a caller hears the demo audio and logs show Exotel event flow.*

## Phase 4: Voice Pipeline 🔴
- [x] 🔴 Decide realtime speech-to-speech vs STT/LLM/TTS components. (M) [rubric: 20%]
  *Acceptance: README explains the choice and tradeoffs.*
- [x] 🔴 Stream inbound PCM to selected STT/realtime engine. (L) [rubric: 15%]
  *Acceptance: caller speech produces partial or final transcripts.*
- [x] 🔴 Maintain per-call conversation context. (M)
  *Acceptance: later turns include relevant prior turns without leaking across calls.*
- [x] 🔴 Generate LLM replies with QWR system instructions. (L)
  *Acceptance: bot answers naturally and can steer back to intake/conversation.*
- [~] 🔴 Stream TTS or realtime model audio back to Exotel. (L) [rubric: 20%]
  *Acceptance: bot audio starts before full reply completion where provider supports it.*
- [~] 🔴 Handle silence and no-input recovery. (M)
  *Acceptance: bot reprompts gracefully before fallback or call end.*
- [ ] 🔴 Handle "didn't catch that" cases. (M)
  *Acceptance: low-confidence or empty transcription triggers a useful recovery prompt.*
- [~] 🔴 Track latency per voice turn. (M) [rubric: 20%]
  *Acceptance: transcript turn records include measured response latency.*
- [ ] 🔴 Create WER test set for Indian-accented English/Hinglish. (M) [rubric: 15%]
  *Acceptance: README reports WER calculation over a small documented sample.*

## Phase 5: Mode Selection 🔴
- [ ] 🔴 Implement mode selection prompt at call start. (M) [rubric: 20%]
  *Acceptance: caller hears four options early in the call.*
- [ ] 🔴 Support voice selection for Think, Challenge, Explore, Guide. (M)
  *Acceptance: spoken mode names map reliably to mode IDs.*
- [ ] 🔴 Support DTMF mode selection keys 1-4. (S)
  *Acceptance: keypad digits select the same modes as speech.*
- [ ] 🔴 Inject Think mode prompt. (S)
  *Acceptance: selected Think calls include the Think behavioral block in the system prompt.*
- [ ] 🔴 Inject Challenge mode prompt. (S)
  *Acceptance: selected Challenge calls pressure-test ideas in the reply style.*
- [ ] 🔴 Inject Explore mode prompt. (S)
  *Acceptance: selected Explore calls teach in short conversational chunks.*
- [ ] 🔴 Inject Guide mode prompt. (S)
  *Acceptance: selected Guide calls use slower structured decision support.*
- [ ] 🔴 Persist selected mode on the call record. (S)
  *Acceptance: dashboard and Supabase show the chosen mode.*
- [ ] 🔴 Apply dual input to every option question. (M)
  *Acceptance: every choice prompt accepts both spoken answers and keypad input.*

## Phase 6: Caller Identity & Intake 🔴
- [ ] 🔴 Normalize inbound caller number to E.164. (S)
  *Acceptance: all phone matching uses one canonical format.*
- [ ] 🔴 Match known caller profile on call start. (M) [rubric: 10%]
  *Acceptance: known callers are greeted by name and linked to the call.*
- [ ] 🔴 Implement unknown-caller anonymous-or-profile choice. (M)
  *Acceptance: caller can proceed anonymously or share details.*
- [ ] 🔴 Capture name from natural speech. (M)
  *Acceptance: extracted name is stored in the profile without invented values.*
- [ ] 🔴 Capture company, role, city, and reason for calling. (M)
  *Acceptance: fields are structured columns, not only raw transcript text.*
- [ ] 🔴 Validate and normalize extracted data. (M)
  *Acceptance: unanswered fields remain null and malformed values are rejected.*
- [ ] 🔴 Personalize later conversation with profile context. (S)
  *Acceptance: bot can naturally use the caller name/context after intake.*
- [ ] 🔴 Document extraction approach. (S)
  *Acceptance: README states scripted, LLM structured output, or hybrid rationale.*

## Phase 7: Web Search & QWR Data 🔴
- [ ] 🔴 Add web search tool integration. (M) [rubric: 5%]
  *Acceptance: factual/current call questions can use live search results.*
- [x] 🔴 Fetch QWR facts from `questionwhatsreal.com`. (M) [rubric: 5%]
  *Acceptance: QWR-specific answers prefer company website content.*
- [ ] 🔴 Add QWR fact sheet fallback. (S)
  *Acceptance: bot can answer baseline QWR questions if website fetch fails.*
- [ ] 🔴 Document LinkedIn fetch limitations. (S)
  *Acceptance: README honestly states what LinkedIn data is or is not fetched.*
- [ ] 🔴 Add source attribution in internal turn metadata. (M)
  *Acceptance: searched answers store source URLs for review.*

## Phase 8: Session Summary & Delivery 🔴
- [ ] 🔴 Detect in-call summary requests. (M) [rubric: 10%]
  *Acceptance: caller can ask for a summary before hanging up.*
- [ ] 🔴 Generate summary from stored transcript. (M)
  *Acceptance: summary includes key points, captured details, and outcome.*
- [ ] 🔴 Capture or reuse delivery destination. (M)
  *Acceptance: email/phone destination comes from profile or call intake.*
- [ ] 🔴 Send summary by email or SMS. (M) [rubric: 10%]
  *Acceptance: delivery provider returns success and status is recorded.*
- [ ] 🔴 Generate summary on call end. (M)
  *Acceptance: completed calls get a summary even if caller did not ask mid-call.*

## Phase 9: Dashboard 🔴
- [ ] 🔴 Build active calls view. (M) [rubric: 5%]
  *Acceptance: dashboard shows live/in-progress calls.*
- [ ] 🔴 Build call history view. (M)
  *Acceptance: dashboard lists completed calls with caller, mode, time, and duration.*
- [ ] 🔴 Build call detail view. (M)
  *Acceptance: detail page shows profile, summary, transcript, and metadata.*
- [ ] 🔴 Add transcript search/filter. (M)
  *Acceptance: user can search historical transcripts.*
- [ ] 🔴 Show recording URL when Exotel provides it. (S)
  *Acceptance: call detail links to recording when available.*
- [ ] 🔴 Show per-turn latency. (S)
  *Acceptance: transcript view includes latency metadata for bot turns.*

## Phase 10: Call Quality Detection 🟡
- [ ] 🟡 Track STT confidence and retry rate. (M)
  *Acceptance: call quality state updates from recognition failures.*
- [ ] 🟡 Track media jitter/packet timing. (M)
  *Acceptance: stream chunk timing anomalies are measured.*
- [ ] 🟡 Adapt prompts for poor line quality. (M)
  *Acceptance: bot shortens and slows prompts when quality drops.*
- [ ] 🟡 Offer DTMF fallback proactively. (M)
  *Acceptance: poor quality prompts include keypad recovery options.*
- [ ] 🟡 Document implemented or proposed call-quality approach. (S)
  *Acceptance: README describes signals, adaptation, and limitations.*

## Phase 11: Testing & Measurement 🔵
- [x] 🔵 Add unit tests for audio chunking. (S)
  *Acceptance: PCM helper tests validate Exotel chunk sizing.*
- [~] 🔵 Add consumer tests for Exotel event dispatch. (M)
  *Acceptance: WebSocket tests cover start, media, DTMF, clear, and stop.*
- [ ] 🔵 Add STT WER measurement script. (M)
  *Acceptance: command outputs WER for the documented test set.*
- [ ] 🔵 Add latency benchmark script. (M)
  *Acceptance: command reports per-turn latency summary.*
- [ ] 🔵 Add end-to-end recorded call artifact. (L)
  *Acceptance: deliverables include a test call recording or dial-in demo.*

## Phase 12: Documentation & Deliverables 🔵
- [x] 🔵 Write architecture section. (S) [rubric: 5%]
  *Acceptance: README explains telephony adapter, voice engine, Supabase, and dashboard boundaries.*
- [ ] 🔵 Add ER diagram. (S)
  *Acceptance: README or docs include profile/call/transcript relationships.*
- [x] 🔵 Document STT/TTS choices and rationale. (S)
  *Acceptance: README names providers and why they were selected.*
- [ ] 🔵 Report measured latency and WER. (S)
  *Acceptance: README includes actual measurements from test runs.*
- [ ] 🔵 Document extraction and diarization decisions. (S)
  *Acceptance: README explains structured intake and speaker labeling approach.*
- [x] 🔵 Document tradeoffs and incomplete optional work. (S)
  *Acceptance: README clearly states known gaps and future improvements.*
- [ ] 🔵 Prepare final GitHub repository. (S)
  *Acceptance: repo includes code, schema, README, and reproducible setup.*
- [ ] 🔵 Prepare dashboard link or screen recording. (M)
  *Acceptance: evaluators can inspect dashboard behavior.*
- [ ] 🔵 Prepare sample delivered summary. (S)
  *Acceptance: deliverables include an email/SMS summary example.*
