-- Migration 002: Skill Fabric tables
-- Creates tables for the skill registry and audit log.

-- Skill registry entries
CREATE TABLE IF NOT EXISTS skills (
    skill_id     TEXT PRIMARY KEY,
    tenant_id    TEXT,
    name         TEXT NOT NULL,
    version      TEXT NOT NULL DEFAULT '1.0.0',
    environment  TEXT NOT NULL DEFAULT 'draft',  -- draft/tested/approved/default
    enabled      BOOLEAN DEFAULT TRUE,
    skill_spec   TEXT NOT NULL,   -- JSON blob (full SkillSpec)
    compiled_skill TEXT,          -- JSON blob (CompiledSkill), NULL until compiled
    created_by   TEXT NOT NULL DEFAULT 'system',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_skills_tenant ON skills(tenant_id);
CREATE INDEX IF NOT EXISTS idx_skills_env    ON skills(tenant_id, environment);

-- Skill audit log
CREATE TABLE IF NOT EXISTS skill_audit_log (
    id           TEXT PRIMARY KEY,
    skill_id     TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    action       TEXT NOT NULL,
    actor        TEXT NOT NULL,
    from_env     TEXT,
    to_env       TEXT,
    details      TEXT DEFAULT '{}',
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_skill_audit ON skill_audit_log(skill_id, timestamp);
