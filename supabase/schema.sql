-- ============================================================================
-- QWR Voice Bot — Supabase Schema
-- Run this in the Supabase SQL Editor to create all required tables.
-- Django models in telephony/models.py mirror this schema exactly.
-- ============================================================================

-- Profiles: caller identity and intake data
CREATE TABLE IF NOT EXISTS telephony_profile (
    id BIGSERIAL PRIMARY KEY,
    phone VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255),
    company VARCHAR(255),
    role VARCHAR(255),
    city VARCHAR(255),
    email VARCHAR(254),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Calls: per-call metadata linked to profile
CREATE TABLE IF NOT EXISTS telephony_call (
    id BIGSERIAL PRIMARY KEY,
    call_sid VARCHAR(255) UNIQUE NOT NULL,
    stream_sid VARCHAR(255),
    from_number VARCHAR(20) NOT NULL DEFAULT '',
    to_number VARCHAR(20) NOT NULL DEFAULT '',
    direction VARCHAR(20) NOT NULL DEFAULT 'incoming'
        CHECK (direction IN ('incoming', 'outgoing')),
    call_state VARCHAR(50) NOT NULL DEFAULT 'greeting'
        CHECK (call_state IN (
            'greeting', 'mode_selection', 'identity_check',
            'unknown_caller_choice', 'intake', 'conversation',
            'summary_confirm', 'ended'
        )),
    selected_mode VARCHAR(100),        -- think, challenge, explore, guide
    duration INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(100) NOT NULL,
    profile_id BIGINT REFERENCES telephony_profile(id) ON DELETE SET NULL,
    completed_on TIMESTAMP WITH TIME ZONE,
    recording_url VARCHAR(500),
    end_reason VARCHAR(255),           -- caller_hangup, no_input_timeout, ai_ended:*
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Transcript turns: speaker-labeled dialogue per call
CREATE TABLE IF NOT EXISTS telephony_transcriptturn (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT REFERENCES telephony_call(id) ON DELETE CASCADE NOT NULL,
    seq_number INTEGER NOT NULL,
    speaker VARCHAR(50) NOT NULL,      -- 'user' or 'assistant'
    text TEXT NOT NULL,
    latency_ms INTEGER,                -- bot response latency in ms
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Summaries: post-call LLM-generated summaries
CREATE TABLE IF NOT EXISTS telephony_summary (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT REFERENCES telephony_call(id) ON DELETE CASCADE UNIQUE NOT NULL,
    summary_text TEXT NOT NULL,
    delivery_status VARCHAR(100) NOT NULL,  -- pending, sent, failed
    destination VARCHAR(255),               -- email or phone
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- ============================================================================
-- Indexes
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_profile_phone ON telephony_profile(phone);
CREATE INDEX IF NOT EXISTS idx_call_call_sid ON telephony_call(call_sid);
CREATE INDEX IF NOT EXISTS idx_call_from_number ON telephony_call(from_number);
CREATE INDEX IF NOT EXISTS idx_call_to_number ON telephony_call(to_number);
CREATE INDEX IF NOT EXISTS idx_call_direction ON telephony_call(direction);
CREATE INDEX IF NOT EXISTS idx_call_status ON telephony_call(status);
CREATE INDEX IF NOT EXISTS idx_call_state ON telephony_call(call_state);
CREATE INDEX IF NOT EXISTS idx_turns_call_id ON telephony_transcriptturn(call_id);

-- Full-text search on transcripts (for dashboard search)
CREATE INDEX IF NOT EXISTS idx_turns_text_fts
    ON telephony_transcriptturn
    USING gin(to_tsvector('english', text));

-- Full-text search on summaries
CREATE INDEX IF NOT EXISTS idx_summary_text_fts
    ON telephony_summary
    USING gin(to_tsvector('english', summary_text));
