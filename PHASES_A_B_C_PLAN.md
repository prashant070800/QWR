# Phases A-B-C Implementation Plan

## Phase A: Data Foundation (Storage Layer)

### Goals
- ✅ Persist calls and transcript turns to Supabase (or local fallback for dev)
- ✅ Create Python storage adapter
- ✅ Test end-to-end storage flow

### Tasks
1. Review current telephony models
2. Create storage.py adapter (Supabase + local fallback)
3. Update ExotelVoicebotConsumer to persist Call + TranscriptTurns
4. Update QWRAgent to call storage on every turn
5. Test with stub STT/TTS in dev

---

## Phase B: Call Flow State Machine

### States
```
GREETING
    ↓
MODE_SELECTION (speech or DTMF: 1=Think, 2=Challenge, 3=Explore, 4=Guide)
    ↓
IDENTITY_CHECK (known caller? → link Profile | unknown? → ask intake or anonymous)
    ↓
INTAKE (collect name, company, role, city, reason)
    ↓
CONVERSATION (free-form Q&A with selected mode prompt)
    ↓
SUMMARY_CONFIRM (offer to email/SMS summary)
    ↓
ENDED
```

### Tasks
1. Create CallStateMachine class
2. Map DTMF digits to mode/option based on state
3. Add mode selection prompt with retry logic
4. Add intake capture (name, company, role, city, reason)
5. Test state transitions

---

## Phase C: Mode Prompts

### Mode Constants (from assignment appendix)
1. **Think**: Encourage critical thinking, ask "What evidence?" 
2. **Challenge**: Devil's advocate, question assumptions
3. **Explore**: Broad discovery, "What else?"
4. **Guide**: Step-by-step guidance, structure

### Tasks
1. Define mode prompts as constants
2. Update QWRAgent to accept selected_mode
3. Inject mode block into system prompt
4. Test each mode produces correct behavioral change

---

## Implementation Order
1. **A1**: Review current models → storage.py adapter
2. **A2**: Supabase schema (or use existing DB)
3. **A3**: Persist turns in agent.py + consumer.py
4. **B1**: CallStateMachine class
5. **B2**: DTMF → option mapping
6. **C1**: Mode prompts
7. **C2**: Test all 4 modes

---

## Files to Create/Update
- `telephony/storage.py` [NEW] - Storage adapter
- `telephony/state_machine.py` [NEW] - CallStateMachine
- `telephony/models.py` [UPDATE] - Add call_state field
- `telephony/consumers.py` [UPDATE] - Integrate storage
- `ai_agent/agent.py` [UPDATE] - Integrate storage, mode injection
- `ai_agent/modes.py` [NEW] - Mode prompts
- `supabase/schema.sql` [UPDATE] - Add state column

---

## Success Criteria ✅
- [ ] Calls persisted to DB with all turns
- [ ] State machine transitions correctly
- [ ] DTMF 1-4 selects mode
- [ ] Each mode produces different behavior
- [ ] Unknown caller intake works
- [ ] End-to-end test call completes
