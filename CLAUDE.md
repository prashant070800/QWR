You are a senior software engineer and technical project manager. I am giving you a 
technical assignment document for building an AI Voice Bot system. Your job is to:

1. Read the entire document carefully
2. Extract EVERY requirement — core, optional, and implied
3. Produce a single, comprehensive `TASKS.md` file

---

## Output format for TASKS.md

Structure the file exactly like this:

# QWR AI Voice Bot — Task List

## Legend
- [ ] = not started | [~] = in progress | [x] = done
- 🔴 CORE = graded, required | 🟡 OPTIONAL = bonus | 🔵 INFRA = setup/scaffolding

---

## Phase 1: Project Setup & Infra 🔵
(all environment, repo, config, dependency tasks)

## Phase 2: Supabase Schema 🔴
(all database design tasks, table by table)

## Phase 3: Telephony Integration 🔴
(Plivo/Twilio/Exotel setup, inbound webhook, DTMF)

## Phase 4: Voice Pipeline 🔴
(STT, LLM, TTS wiring, streaming, latency measurement)

## Phase 5: Mode Selection 🔴
(4 modes, prompt injection, voice + keypad dual input)

## Phase 6: Caller Identity & Intake 🔴
(profile matching, structured extraction, anonymous flow)

## Phase 7: Web Search & QWR Data 🔴
(Tavily/search integration, questionwhatsreal.com fetch)

## Phase 8: Session Summary & Delivery 🔴
(summary generation, email/SMS sending)

## Phase 9: Dashboard 🔴
(Django templates, live calls, history, search)

## Phase 10: Call Quality Detection 🟡
(optional adaptive behavior for poor networks)

## Phase 11: Testing & Measurement 🔵
(WER test set, latency benchmarks, end-to-end test call)

## Phase 12: Documentation & Deliverables 🔵
(README, ER diagram, schema export, recorded call)

---

## Rules for each task entry:
- Write it as a concrete, actionable engineering task (not vague)
- Add a one-line acceptance criterion after each task in italics
- Group sub-tasks with indentation using `-`
- Flag dependencies with `⚠️ Depends on: Phase X`
- Add estimated complexity: `(S)` small ~1-2hrs, `(M)` medium ~3-5hrs, `(L)` large ~6-8hrs+
- If a task maps directly to an evaluation rubric item, add its weight e.g. `[rubric: 20%]`

---

## Additional instructions:
- Do NOT skip optional tasks — mark them 🟡 but include them
- Do NOT merge unrelated concerns into one task
- Where the document says "your choice", create a task for making + documenting that decision
- Include tasks for error handling, edge cases, and graceful degradation
- Include a task for each README section the document requires
- The final task count should be 60–90 individual tasks

Now generate the complete TASKS.md file.