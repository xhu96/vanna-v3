# Database Migrations

This directory contains SQL migration scripts for the personalization and skill fabric subsystems.

## Applying Migrations

If using a SQL database backend (PostgreSQL, SQLite, etc.), run these scripts in order:

1. `001_personalization_tables.sql` — User/tenant profiles, glossary, session memory
2. `002_skill_tables.sql` — Skills registry and audit log

### Example (PostgreSQL)

```bash
psql -U postgres -d vanna -f src/vanna/migrations/001_personalization_tables.sql
psql -U postgres -d vanna -f src/vanna/migrations/002_skill_tables.sql
```

### Example (SQLite)

```bash
sqlite3 vanna.db < src/vanna/migrations/001_personalization_tables.sql
sqlite3 vanna.db < src/vanna/migrations/002_skill_tables.sql
```

## Notes

- All migrations are **additive** (no existing tables are dropped or altered)
- Default in-memory stores do not require these migrations
- All columns have safe defaults for backward compatibility
