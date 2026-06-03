-- Profiles table to store caller information
CREATE TABLE IF NOT EXISTS profiles (
    id BIGSERIAL PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    company TEXT,
    role TEXT,
    city TEXT,
    email TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Calls table to track individual calls
CREATE TABLE IF NOT EXISTS calls (
    id BIGSERIAL PRIMARY KEY,
    call_sid TEXT UNIQUE NOT NULL,
    stream_sid TEXT,
    from_number TEXT NOT NULL,
    to_number TEXT,
    direction TEXT NOT NULL DEFAULT 'incoming' CHECK (direction IN ('incoming', 'outgoing')),
    selected_mode TEXT, -- Think, Challenge, Explore, Guide
    duration INTEGER DEFAULT 0, -- Duration in seconds
    status TEXT NOT NULL, -- e.g. initiated, in-progress, completed, failed
    profile_id BIGINT REFERENCES profiles(id) ON DELETE SET NULL,
    completed_on TIMESTAMP WITH TIME ZONE,
    recording_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Transcript Turns table to log individual dialogue turns
CREATE TABLE IF NOT EXISTS transcript_turns (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT REFERENCES calls(id) ON DELETE CASCADE NOT NULL,
    seq_number INTEGER NOT NULL,
    speaker TEXT NOT NULL, -- 'user' or 'assistant'
    text TEXT NOT NULL,
    latency_ms INTEGER, -- measured response latency in ms
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Summaries table to store post-call summaries
CREATE TABLE IF NOT EXISTS summaries (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT REFERENCES calls(id) ON DELETE CASCADE UNIQUE NOT NULL,
    summary_text TEXT NOT NULL,
    delivery_status TEXT NOT NULL, -- pending, sent, failed, none
    destination TEXT, -- email address or phone number
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Indexes for performance lookups
CREATE INDEX IF NOT EXISTS idx_profiles_phone ON profiles(phone);
CREATE INDEX IF NOT EXISTS idx_calls_call_sid ON calls(call_sid);
CREATE INDEX IF NOT EXISTS idx_calls_from_number ON calls(from_number);
CREATE INDEX IF NOT EXISTS idx_calls_to_number ON calls(to_number);
CREATE INDEX IF NOT EXISTS idx_calls_direction ON calls(direction);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_completed_on ON calls(completed_on);
CREATE INDEX IF NOT EXISTS idx_transcript_turns_call_id ON transcript_turns(call_id);

-- Postgres GIN full-text search index for searching transcripts
CREATE INDEX IF NOT EXISTS idx_transcript_turns_text_fts ON transcript_turns USING gin(to_tsvector('english', text));
