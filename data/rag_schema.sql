-- OptiBot v2 — RAG schema for Supabase
-- Run this in Supabase SQL Editor to set up pgvector + call summaries

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Call summaries for RAG retrieval
CREATE TABLE IF NOT EXISTS call_summaries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    mutuelle TEXT NOT NULL,
    dossier_type TEXT DEFAULT 'optique',
    summary TEXT NOT NULL,
    outcome TEXT NOT NULL,  -- 'resolved', 'callback', 'failed', 'escalated'
    key_learnings TEXT[] DEFAULT '{}',
    action_sequence TEXT[] DEFAULT '{}',
    extracted_data JSONB DEFAULT '{}',
    embedding vector(1536),  -- OpenAI text-embedding-3-small dimension
    duration_seconds FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_call_summaries_tenant ON call_summaries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_call_summaries_mutuelle ON call_summaries(mutuelle);
CREATE INDEX IF NOT EXISTS idx_call_summaries_created ON call_summaries(created_at DESC);

-- pgvector index for similarity search
CREATE INDEX IF NOT EXISTS idx_call_summaries_embedding
    ON call_summaries USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- RLS for tenant isolation
ALTER TABLE call_summaries ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_read_own ON call_summaries
    FOR SELECT USING (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY tenant_insert_own ON call_summaries
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- RPC: Vector similarity search (primary — uses mistral-embed 1024-dim)
CREATE OR REPLACE FUNCTION match_call_summaries_vector(
    query_embedding vector(1536),
    filter_tenant TEXT,
    filter_mutuelle TEXT DEFAULT NULL,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id BIGINT,
    tenant_id TEXT,
    mutuelle TEXT,
    dossier_type TEXT,
    summary TEXT,
    outcome TEXT,
    key_learnings TEXT[],
    action_sequence TEXT[],
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cs.id,
        cs.tenant_id,
        cs.mutuelle,
        cs.dossier_type,
        cs.summary,
        cs.outcome,
        cs.key_learnings,
        cs.action_sequence,
        1 - (cs.embedding <=> query_embedding) AS similarity
    FROM call_summaries cs
    WHERE cs.tenant_id = filter_tenant
      AND cs.embedding IS NOT NULL
      AND (filter_mutuelle IS NULL OR cs.mutuelle = filter_mutuelle)
    ORDER BY cs.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- RPC: Text-based fallback search (when embedding fails)
CREATE OR REPLACE FUNCTION match_call_summaries(
    query_text TEXT,
    filter_tenant TEXT,
    filter_mutuelle TEXT DEFAULT NULL,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id BIGINT,
    tenant_id TEXT,
    mutuelle TEXT,
    dossier_type TEXT,
    summary TEXT,
    outcome TEXT,
    key_learnings TEXT[],
    action_sequence TEXT[],
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cs.id,
        cs.tenant_id,
        cs.mutuelle,
        cs.dossier_type,
        cs.summary,
        cs.outcome,
        cs.key_learnings,
        cs.action_sequence,
        ts_rank(to_tsvector('french', cs.summary), plainto_tsquery('french', query_text))::FLOAT AS similarity
    FROM call_summaries cs
    WHERE cs.tenant_id = filter_tenant
      AND (filter_mutuelle IS NULL OR cs.mutuelle = filter_mutuelle)
    ORDER BY similarity DESC
    LIMIT match_count;
END;
$$;
