-- Mutuelle memory schema — persistent learning across calls
-- Ported from OptiBot v1 tools/memory.py

CREATE TABLE IF NOT EXISTS mutuelles (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nom TEXT UNIQUE NOT NULL,
    nom_affiche TEXT NOT NULL,
    svi_chemin TEXT DEFAULT '',
    numero_direct TEXT DEFAULT '',
    horaires TEXT DEFAULT '',
    delai_moyen_jours FLOAT DEFAULT 0,
    derniere_interaction TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS apprentissages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mutuelle_nom TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('astuce', 'piege')),
    contenu TEXT NOT NULL,
    occurrences INT DEFAULT 1,
    derniere_utilisation TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (mutuelle_nom, type, contenu)
);

CREATE TABLE IF NOT EXISTS interlocuteurs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mutuelle_nom TEXT NOT NULL,
    nom TEXT NOT NULL,
    role TEXT DEFAULT '',
    note TEXT DEFAULT '',
    derniere_interaction TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (mutuelle_nom, nom)
);

CREATE INDEX IF NOT EXISTS idx_apprentissages_mutuelle ON apprentissages(mutuelle_nom);
CREATE INDEX IF NOT EXISTS idx_interlocuteurs_mutuelle ON interlocuteurs(mutuelle_nom);

-- RPC: get full memory for a mutuelle (single call before each outbound call)
CREATE OR REPLACE FUNCTION get_mutuelle_memory(nom_mutuelle TEXT)
RETURNS JSON
LANGUAGE plpgsql
AS $$
DECLARE
    result JSON;
    mut_row RECORD;
BEGIN
    SELECT * INTO mut_row FROM mutuelles WHERE nom = nom_mutuelle LIMIT 1;

    IF NOT FOUND THEN
        RETURN '{}'::JSON;
    END IF;

    SELECT json_build_object(
        'nom', mut_row.nom,
        'nom_affiche', mut_row.nom_affiche,
        'svi_chemin', mut_row.svi_chemin,
        'numero_direct', mut_row.numero_direct,
        'horaires', mut_row.horaires,
        'delai_moyen_jours', mut_row.delai_moyen_jours,
        'astuces', COALESCE((
            SELECT json_agg(json_build_object('contenu', a.contenu, 'occurrences', a.occurrences))
            FROM apprentissages a WHERE a.mutuelle_nom = nom_mutuelle AND a.type = 'astuce'
            ORDER BY a.occurrences DESC LIMIT 5
        ), '[]'::JSON),
        'pieges', COALESCE((
            SELECT json_agg(json_build_object('contenu', p.contenu, 'occurrences', p.occurrences))
            FROM apprentissages p WHERE p.mutuelle_nom = nom_mutuelle AND p.type = 'piege'
            ORDER BY p.occurrences DESC LIMIT 5
        ), '[]'::JSON),
        'interlocuteurs', COALESCE((
            SELECT json_agg(json_build_object('nom', i.nom, 'role', i.role, 'note', i.note))
            FROM interlocuteurs i WHERE i.mutuelle_nom = nom_mutuelle
            ORDER BY i.derniere_interaction DESC LIMIT 5
        ), '[]'::JSON)
    ) INTO result;

    RETURN result;
END;
$$;

-- RPC: upsert mutuelle base data after a call
CREATE OR REPLACE FUNCTION upsert_mutuelle_memory(
    p_nom TEXT,
    p_nom_affiche TEXT,
    p_svi_chemin TEXT DEFAULT '',
    p_delai_jours FLOAT DEFAULT 0,
    p_interlocuteur_nom TEXT DEFAULT '',
    p_interlocuteur_role TEXT DEFAULT ''
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO mutuelles (nom, nom_affiche, svi_chemin, delai_moyen_jours, derniere_interaction)
    VALUES (p_nom, p_nom_affiche, p_svi_chemin, p_delai_jours, NOW())
    ON CONFLICT (nom) DO UPDATE SET
        nom_affiche = EXCLUDED.nom_affiche,
        svi_chemin = CASE WHEN EXCLUDED.svi_chemin != '' THEN EXCLUDED.svi_chemin ELSE mutuelles.svi_chemin END,
        delai_moyen_jours = CASE WHEN EXCLUDED.delai_moyen_jours > 0 THEN EXCLUDED.delai_moyen_jours ELSE mutuelles.delai_moyen_jours END,
        derniere_interaction = NOW();

    IF p_interlocuteur_nom != '' THEN
        INSERT INTO interlocuteurs (mutuelle_nom, nom, role, derniere_interaction)
        VALUES (p_nom, p_interlocuteur_nom, p_interlocuteur_role, NOW())
        ON CONFLICT (mutuelle_nom, nom) DO UPDATE SET
            role = CASE WHEN EXCLUDED.role != '' THEN EXCLUDED.role ELSE interlocuteurs.role END,
            derniere_interaction = NOW();
    END IF;
END;
$$;

-- RPC: upsert a learning (astuce or piege) with atomic increment
CREATE OR REPLACE FUNCTION upsert_apprentissage(
    p_mutuelle_nom TEXT,
    p_type TEXT,
    p_contenu TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO apprentissages (mutuelle_nom, type, contenu, occurrences, derniere_utilisation)
    VALUES (p_mutuelle_nom, p_type, p_contenu, 1, NOW())
    ON CONFLICT (mutuelle_nom, type, contenu) DO UPDATE SET
        occurrences = apprentissages.occurrences + 1,
        derniere_utilisation = NOW();
END;
$$;

-- ═══════════════════════════════════════════════════════════════════════
-- Phase 6: Dossier-level open items / followups (cross-call continuity)
-- Research: Microsoft call-center-ai has "reminders" — we need the same
-- for multi-call dossier workflows (e.g. "document X pending since date Y").
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dossier_followups (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    mutuelle_nom TEXT NOT NULL,
    dossier_ref TEXT NOT NULL,
    state TEXT NOT NULL, -- 'awaiting_doc' | 'callback_scheduled' | 'resolved'
    note TEXT,
    callback_after TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (tenant_id, dossier_ref)
);
CREATE INDEX IF NOT EXISTS idx_followups_mutuelle ON dossier_followups(tenant_id, mutuelle_nom) WHERE state != 'resolved';
CREATE INDEX IF NOT EXISTS idx_followups_dossier ON dossier_followups(tenant_id, dossier_ref);

ALTER TABLE dossier_followups ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_rw_followups ON dossier_followups
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- RPC: upsert followup (called from memoriser_appel when suivi_requis is set)
CREATE OR REPLACE FUNCTION upsert_followup(
    p_tenant_id TEXT,
    p_mutuelle_nom TEXT,
    p_dossier_ref TEXT,
    p_state TEXT,
    p_note TEXT DEFAULT NULL,
    p_callback_after TIMESTAMPTZ DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO dossier_followups (tenant_id, mutuelle_nom, dossier_ref, state, note, callback_after)
    VALUES (p_tenant_id, p_mutuelle_nom, p_dossier_ref, p_state, p_note, p_callback_after)
    ON CONFLICT (tenant_id, dossier_ref) DO UPDATE SET
        state = EXCLUDED.state,
        note = COALESCE(EXCLUDED.note, dossier_followups.note),
        callback_after = COALESCE(EXCLUDED.callback_after, dossier_followups.callback_after),
        updated_at = NOW(),
        resolved_at = CASE WHEN EXCLUDED.state = 'resolved' THEN NOW() ELSE NULL END;
END;
$$;

-- Staleness: apprentissages older than 90 days + low occurrence get pruned on load
-- This filter is applied in MutuelleMemory.load() Python code, not in the RPC
-- (to avoid migrating the existing get_mutuelle_memory RPC).
