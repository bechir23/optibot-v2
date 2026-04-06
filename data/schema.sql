-- OptiBot v2 — Core DB schema for Supabase
-- Run this in Supabase SQL Editor

-- Tenants (one optician = one tenant)
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    max_concurrent_calls INT DEFAULT 5,
    llm_model TEXT DEFAULT 'mistral-small-latest',
    tts_voice TEXT DEFAULT 'french-female-professional',
    greeting TEXT DEFAULT 'Bonjour, je vous appelle de la part de {name} concernant un dossier de remboursement.',
    ivr_target TEXT DEFAULT 'remboursements optiques',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Action templates (dynamic, loaded from DB instead of hardcoded)
CREATE TABLE IF NOT EXISTS action_templates (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    template TEXT NOT NULL,
    description TEXT,
    requires_data JSONB DEFAULT '[]',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Action outcomes (tracks success per mutuelle)
CREATE TABLE IF NOT EXISTS action_outcomes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action_id TEXT REFERENCES action_templates(id),
    call_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    mutuelle TEXT,
    success BOOLEAN,
    confidence FLOAT,
    response_quality FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outcomes_action ON action_outcomes(action_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_mutuelle ON action_outcomes(mutuelle);

-- Mutuelle action overrides (per-mutuelle success rates + custom wording)
CREATE TABLE IF NOT EXISTS mutuelle_action_overrides (
    mutuelle TEXT NOT NULL,
    action_id TEXT REFERENCES action_templates(id),
    template_override TEXT,
    success_rate FLOAT DEFAULT 0.5,
    sample_count INT DEFAULT 0,
    PRIMARY KEY (mutuelle, action_id)
);

-- Mutuelle IVR maps (known phone tree structures)
CREATE TABLE IF NOT EXISTS mutuelle_ivr_maps (
    mutuelle TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    ivr_tree JSONB NOT NULL,
    avg_wait_minutes FLOAT DEFAULT 10,
    best_call_time TEXT DEFAULT '10h-12h',
    notes TEXT DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Dynamic mutuelle aliases (STT normalization, fuzzy canonicalization)
CREATE TABLE IF NOT EXISTS mutuelle_aliases (
    mutuelle TEXT NOT NULL,
    alias TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    source TEXT DEFAULT 'manual',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (mutuelle, alias)
);

CREATE INDEX IF NOT EXISTS idx_mutuelle_aliases_alias ON mutuelle_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_mutuelle_aliases_mutuelle ON mutuelle_aliases(mutuelle);

-- Dynamic SSML abbreviations (telephony pronunciation dictionary)
CREATE TABLE IF NOT EXISTS ssml_abbreviations (
    key TEXT PRIMARY KEY,
    expansion TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Dynamic SSML regex patterns (normalization rules)
CREATE TABLE IF NOT EXISTS ssml_regex_patterns (
    name TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,
    flags TEXT DEFAULT '',
    active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Dynamic SSML month dictionary (date expansion)
CREATE TABLE IF NOT EXISTS ssml_month_names (
    month_key TEXT PRIMARY KEY,
    month_name TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Call log (every call tracked)
CREATE TABLE IF NOT EXISTS call_log (
    id TEXT PRIMARY KEY,  -- room name / call_sid
    tenant_id TEXT NOT NULL,
    mutuelle TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    dossier_id TEXT,
    status TEXT DEFAULT 'initiated',  -- initiated, connected, completed, failed
    phase TEXT DEFAULT 'dialing',
    outcome TEXT,
    extracted_data JSONB DEFAULT '{}',
    tools_called TEXT[] DEFAULT '{}',
    duration_seconds FLOAT DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_log_tenant ON call_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_call_log_status ON call_log(status);

-- RLS on all tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_read_tenants ON tenants
    FOR SELECT USING (id = current_setting('app.tenant_id', true));

CREATE POLICY tenant_read_outcomes ON action_outcomes
    FOR SELECT USING (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY tenant_read_calls ON call_log
    FOR SELECT USING (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY tenant_insert_calls ON call_log
    FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY tenant_update_calls ON call_log
    FOR UPDATE USING (tenant_id = current_setting('app.tenant_id', true));
