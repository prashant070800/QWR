# QWR Assignment Requirements — Implementation Status

> Source: `QWR_Technical_Assignment_AI_Voice_Bot.pdf`
> Last audited: 2026-06-07

---

## Evaluation Rubric Summary

| # | Criterion | Weight | Status |
|---|-----------|--------|--------|
| 1 | Voice naturalness & latency | 20% | 🟢 Done (README pending) |
| 2 | Transcription accuracy & WER measurement | 15% | 🟢 Done (measure pending) |
| 3 | Mode selection + mode prompts + DTMF dual input | 20% | 🟢 Done |
| 4 | Web search + live company data (questionwhatsreal.com) | 5% | 🔴 Not done |
| 5 | Supabase schema & speaker-labeled storage | 15% | 🟡 Partial |
| 6 | Caller identity / anonymous flow & extraction | 10% | 🔴 Not done |
| 7 | Session summary report (email/SMS or link) | 10% | 🟡 Partial |
| 8 | Dashboard (live + history + search) | 5% | 🔴 Not done |
| 9 | Decoupled architecture & README clarity | 5% | 🟡 Partial |

---

## 1. Voice Backend (CORE) — 20%

### 1.1 Inbound calling via telephony provider
- [x] Exotel WebSocket integration (`telephony/consumers.py`, `consumers_live.py`)
- [x] Inbound call handling with stream_sid, call_sid

### 1.2 Voice pipeline / realtime engine
- [x] Legacy STT → LLM → TTS pipeline (`consumers.py`)
- [x] Gemini Live API audio-to-audio engine (`consumers_live.py`, `ai_agent/gemini_live.py`)
- [x] Configurable engine via `VOICE_ENGINE` env var
- [x] Streaming output (Gemini Live streams audio before full reply)

### 1.3 Measured latency per turn
- [x] Per-turn latency tracking in `LiveTranscript.latency_ms`
- [x] Latency logged per turn (`💬 Turn #N | Latency: XXXms`)
- [ ] **Latency stored in transcript_turns table** — latency_ms column exists but not consistently populated
- [ ] **Latency reported in README** — need measured averages

### 1.4 Graceful silence / "didn't catch that" / call end
- [x] Silence watchdog with graduated recovery (`telephony/silence_watchdog.py`)
- [x] AI-initiated call end via Gemini function calling (`end_call` tool)
- [x] `end_reason` field on Call model
- [x] **"Didn't catch that" re-prompt** — system prompt instructs Gemini to ask caller to repeat

### 1.5 Voice quality justification in README
- [ ] State which voice engine and why (Gemini Live vs alternatives)
- [ ] Report measured latency numbers

---

## 2. Transcription Accuracy & WER — 15%

### 2.1 Transcription
- [x] Gemini Live native input/output transcription enabled
- [x] Transcriptions captured and logged per turn

### 2.2 WER measurement
- [ ] **Create a small test set** (5-10 utterances, Indian-accented English / Hinglish)
- [ ] **Compute WER** against ground truth
- [ ] **Report WER in README**
- [ ] **Note how Indian-accented English / Hinglish is handled**

---

## 3. Mode Selection — 20%

### 3.1 Four conversation modes
- [x] **THINK mode prompt** — injected in system prompt
- [x] **CHALLENGE mode prompt** — injected in system prompt
- [x] **EXPLORE mode prompt** — injected in system prompt
- [x] **GUIDE mode prompt** — injected in system prompt

### 3.2 Mode selection flow
- [x] **Bot offers mode selection early in call** (voice + DTMF) — system prompt instructs this
- [x] **Voice-based mode selection** ("say Challenge mode") — Gemini interprets naturally
- [x] **DTMF keypad mode selection** (press 1-4) — forwarded as text, Gemini interprets
- [x] **Selected mode injected into system prompt** — all 4 modes pre-loaded, `select_mode` tool triggers behavior shift
- [x] **Mode stored in call record** — `select_mode` callback updates `selected_mode` in DB

### 3.3 Dual input on ALL option questions
- [x] **Every choice question accepts voice + DTMF** — system prompt instructs dual input
- [x] **Known/anonymous caller prompt accepts dual input** — (to be tested with caller identity flow)
- [x] **Yes/no confirmations accept dual input** — DTMF forwarded as text
- [x] **No-input and unrecognized-input handled gracefully** — re-prompt + default to Think

---

## 4. Web Search & Live Company Data — 5%

### 4.1 Web search during calls
- [ ] **Web search tool enabled** for factual / current questions
- [x] QWR fact sheet hardcoded in system prompt (static, not live)

### 4.2 Live data from questionwhatsreal.com
- [ ] **Fetch from questionwhatsreal.com** as primary live source
- [ ] **Products, industries, about pages scraped/fetched**

### 4.3 LinkedIn (optional)
- [ ] LinkedIn public data (optional, note limitations)

---

## 5. Supabase Data Layer — 15%

### 5.1 Schema
- [x] `profiles` table — phone, name, company, role, city, email
- [x] `calls` table — call_sid, stream_sid, from_number, to_number, direction, status, duration, selected_mode, profile link, end_reason, call_state
- [x] `transcript_turns` table — call FK, seq_number, speaker, text, latency_ms
- [x] `summaries` table — call FK, summary_text, delivery_status, destination
- [ ] **Using actual Supabase** — currently local SQLite/Django ORM, not Supabase PostgreSQL

### 5.2 Caller identity flow
- [ ] **Match caller E.164 number against profiles on call start**
- [ ] **Known caller → greet by name, link to profile**
- [ ] **Unknown caller → offer to collect details or anonymous mode**
- [x] Profile model with E.164 normalization
- [x] Call → Profile FK relationship exists

### 5.3 Speaker-labeled transcription (diarization)
- [x] Turn-level speaker labels (`user` vs `assistant`) stored
- [x] Gemini Live provides separate input/output transcription

---

## 6. Conversational Intake & Extraction — 10%

### 6.1 Intake flow for unknown callers
- [ ] **Bot runs short intake** — name, company, role, city, reason for calling
- [ ] **Extracted from natural speech into structured fields**
- [ ] **Validated/normalized before storage** (E.164, no hallucinated values)
- [ ] **Profile personalization** — bot uses captured name/context in later turns

### 6.2 Extraction approach
- [ ] **State approach in README** (scripted slot-filling, LLM structured output, or hybrid)

---

## 7. Session Summary Report — 10%

### 7.1 Summary generation
- [x] Post-call summary generated via LLM (`telephony/signals.py`)
- [x] Summary stored in `summaries` table
- [ ] **Mid-call summary on caller request** ("give me a summary")

### 7.2 Summary delivery
- [x] Telegram notification (`telephony/notifications.py`)
- [ ] **Email delivery** (Resend, SendGrid, or SES)
- [ ] **SMS delivery** (via Exotel or Twilio)
- [ ] **Contact destination from profile or captured during call**

---

## 8. Dashboard — 5%

### 8.1 Web UI
- [x] Django Admin with Call, Profile, TranscriptTurn, Summary views (`telephony/admin.py`)
- [ ] **Dedicated dashboard UI** — live/active calls + history
- [ ] **Per-call detail view** — speaker-labeled transcript, duration, linked profile, latency
- [ ] **Transcript search / filter** (full-text search)
- [ ] **Recording playback** (if available)

---

## 9. Architecture & README — 5%

### 9.1 Decoupled architecture
- [x] Voice engine decoupled from telephony adapter (separate `gemini_live.py` vs `consumers_live.py`)
- [x] Dashboard (admin) reads from DB, not in call path
- [x] Configurable engine via env vars

### 9.2 README
- [x] Basic README exists
- [ ] **Architecture + ER diagram**
- [ ] **STT/TTS choices and rationale**
- [ ] **Measured latency and WER**
- [ ] **Extraction and diarization decisions**
- [ ] **Tradeoffs documented**

---

## Deliverables Checklist

- [x] Dial-in number (Exotel configured)
- [ ] **Sample recorded call** (if not keeping paid number)
- [ ] **Sample summary delivered by email or SMS**
- [x] Telegram summary delivery works
- [x] Supabase schema (Django models = schema)
- [ ] **SQL export or screenshot of schema**
- [x] GitHub repository
- [ ] **README with all required sections**

---

## Priority Implementation Order

| Priority | Feature | Weight | Effort |
|----------|---------|--------|--------|
| **P0** | Mode Selection + DTMF + mode prompts | 20% | Medium |
| **P1** | Caller identity / anonymous flow + intake extraction | 10% | Medium |
| **P2** | Web search + live company data | 5% | Low |
| **P3** | Dashboard (beyond Django Admin) | 5% | Medium |
| **P4** | WER measurement harness | 15% | Low |
| **P5** | Email/SMS summary delivery | 10% (partial) | Low |
| **P6** | README polish (architecture, ER, rationale) | 5% | Low |
| **P7** | Supabase migration (SQLite → Supabase PG) | 15% (partial) | Medium |
