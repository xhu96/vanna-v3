-- Migration 001: Personalization tables
-- Creates tables for user profiles, tenant profiles, glossary entries,
-- and session memory. All columns have safe defaults.

-- User profiles (durable, opt-in)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id          TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    locale           TEXT,
    currency         TEXT,
    fiscal_year_start_month INTEGER,
    date_format      TEXT,
    number_format    TEXT,
    department_tags  TEXT DEFAULT '[]',    -- JSON array
    role_tags        TEXT DEFAULT '[]',    -- JSON array
    preferred_chart_type  TEXT,
    preferred_table_style TEXT,
    personalization_enabled BOOLEAN DEFAULT FALSE,
    provenance       TEXT DEFAULT '{}',    -- JSON object
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, tenant_id)
);

-- Tenant profiles (tenant-wide defaults)
CREATE TABLE IF NOT EXISTS tenant_profiles (
    tenant_id        TEXT PRIMARY KEY,
    default_locale   TEXT,
    default_currency TEXT,
    fiscal_year_start_month INTEGER,
    default_date_format  TEXT,
    default_number_format TEXT,
    personalization_enabled BOOLEAN DEFAULT FALSE,
    session_memory_retention_days INTEGER DEFAULT 7,
    provenance       TEXT DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Glossary entries (tenant-scoped, optional user overrides)
CREATE TABLE IF NOT EXISTS glossary_entries (
    entry_id     TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    user_id      TEXT,                     -- NULL = tenant-level
    term         TEXT NOT NULL,
    synonyms     TEXT DEFAULT '[]',        -- JSON array
    definition   TEXT NOT NULL,
    category     TEXT,
    approved     BOOLEAN DEFAULT FALSE,
    approved_by  TEXT,
    provenance   TEXT DEFAULT '{}',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_glossary_tenant ON glossary_entries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_glossary_term   ON glossary_entries(tenant_id, term);

-- Session memory (ephemeral, auto-expiring)
CREATE TABLE IF NOT EXISTS session_memories (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    content      TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at   TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_mem_user ON session_memories(user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_session_mem_exp  ON session_memories(expires_at);
