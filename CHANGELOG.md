# Changelog

All notable changes to this fork are documented here.
Versioning follows [Semantic Versioning](https://semver.org/).
See [`VERSION.txt`](VERSION.txt) for the current release.

This fork builds on top of [vanna-ai/vanna](https://github.com/vanna-ai/vanna) (upstream v2 baseline).

---

## [Upcoming v3.3]

### Planned

- **Webhook ingestion endpoint** — Generic HTTP endpoint for asynchronous event ingestion.
- **Data Contract Hook** — Integration with Pandera for structural validation of query result sets.
- **Approval Lifecycle Hook** — Pluggable human-in-the-loop governance for sensitive queries.
- **Watch Goal Tool + APScheduler** — Autonomously track metrics in the background and alert on deviations.
- **Self-Improving Skill Drafts** — System automatically drafts improvements to skill packs based on user correction history.

---

## [3.2.0]

### Added — Data Engineering OS

- **`DbtDeployTool`** (`src/vanna/tools/dbt_deploy.py`) — Converts a confirmed SQL query into a deployable dbt model: renders `model.sql` + `schema.yml`, runs `dbt compile` + `dbt test`, commits to a new branch, and opens a GitHub PR with test output. Returns a `ToolResult` with a link to the PR or the local path on failure.
- **Column-level Lineage** (`src/vanna/core/lineage/column_lineage.py`) — Best-effort column-level lineage extraction from execution queries using `SQLGlot`.
- **`dbt` optional dependency group** (`pyproject.toml [de]`) — `PyGitHub>=2.3.0`, `dbt-core>=1.7.0`, `sqlglot>=20.0.0`.
- **`VERSION.txt`** — Single source of truth for the project version. Docs now reference this file rather than hardcoding version strings.

### Changed

- `papers/data_engineering_os_vision.md` — Reframed from a marketing "Vision Paper" to a transparent **Vision / Roadmap** document with per-pillar status (`planned` / `in progress`) and a link to the changelog.
- `docs/v3/architecture-and-design.md`, `docs/v3/implementation-plan.md` — Removed hardcoded "v3.2" version strings; docs now stay version-agnostic.
- `docs/v3/glossary.md`, `docs/v3/personalization.md`, `docs/v3/skill-lifecycle.md` — API endpoint tables marked as **"Planned — not yet registered"** (the `/api/v1/` prefix is not currently active in the server).
- `README.md` — Web component example and Python snippet comment updated from stale `/api/vanna/v2/chat_sse` endpoint to the v3 endpoint `/api/vanna/v3/chat/events`. External Vanna AI doc links labelled _(upstream docs — fork APIs may differ)_.
- `requirements.txt` — Added `scipy` and `nest_asyncio` (were in `pyproject.toml` but missing here); added canonical install instructions as header comment.
- `pyproject.toml` — Bumped version `3.1.0` → `3.2.0`.

### Fixed

- `papers/ai-sql-accuracy-2023-08-17.md` — Removed retroactively injected OpenRouter entry (#5) that was never part of the original August 2023 study and broke the paper's stated trial count (180 = 3 LLMs × 3 strategies × 20 questions).

---

## [3.1.0]

### Added — Skill Fabric & Personalization

- **Skill Fabric** (`src/vanna/skills/`) — Declarative YAML skill packs (`SkillSpec`) with a governed lifecycle: `draft → tested → approved → default`. Includes `SkillCompiler`, `ApprovalWorkflow`, `SkillRegistry`, and `InMemorySkillRegistryStore`. Full RBAC, eval gates, and audit logging.
- **Two reference skill packs** (`skill_packs/retail_ops_basics/`, `skill_packs/uk_accounting/`) — Immediately usable templates for retail and UK accounting domains (15 eval questions each).
- **Personalization system** (`src/vanna/personalization/`) — Double opt-in (tenant + user) profile storage with PII redaction (via Microsoft Presidio logs), session memory with configurable TTL, GDPR export/delete, and `PreferenceResolverEnhancer` that injects user context deterministically into the system prompt.
- **Glossary & Ontology** (`src/vanna/personalization/models.py`, `GlossaryService`) — Tenant-scoped term definitions + synonyms injected into the LLM system prompt. Approval workflow: user-created entries, admin-approved injection.
- **Tools** — `export_data.py` added for profile exporting. FastApi routes for personalization (`personalization_routes.py`) and skills (`skill_routes.py`).
- **OpenRouter Integration** — Formal integration for OpenRouter LLM added.
- **Schema Drift Sync** — Portable INFORMATION_SCHEMA snapshots, hash-based diffing, and scheduler-compatible sync service (`src/vanna/services/schema_sync.py`). On-demand endpoint `POST /api/vanna/v3/schema/sync` + status `GET /api/vanna/v3/schema/status`.
- **Feedback Loop** — `src/vanna/services/feedback.py` endpoint `POST /api/vanna/v3/feedback` captures explicit feedback (thumbs-down + corrected SQL) and patches agent memory with weighted corrections.
- **Eval Harness** — Configurable score delta CI gates (`src/evals/`).
- **Tox environments for personalization and skills** — `py311-personalization`, `py311-skills`.
- **UI Components** — New interactive components added (`task_list.py`, `log_viewer.py`) and various styling updates (`vanna-design-tokens.ts`).
- **Test Coverage** — E2E tests added for Personalization, Skills, Profile Services, and Gemini/OpenRouter flows.

### Changed

- Expanded integrations: DataHub, Cube, Flink, and Great Expectations adapters began scaffolding.
- Agent memory now supports weighted corrective patches from user feedback.
- `ToolRegistry` now exposes tool call lineage hooks used by the lineage collector.

### Security

- Pre-commit hooks added for SQL injection guards and unsafe endpoint detection.

---

## [3.0.0]

### Summary

First major fork release — a production-grade overhaul of upstream Vanna v2, focused on security-by-default, typed streaming contracts, and enterprise observability.

### Added

- **Typed Streaming Event Contract (v3)** — Versioned SSE/poll envelope (`event_version: "v3"`) at `POST /api/vanna/v3/chat/events` and `POST /api/vanna/v3/chat/poll`. All event types (`status`, `tool_start`, `tool_result`, `assistant_text`, `table_result`, `chart_spec`, `lineage`, `warning`, `error`, `done`) are typed Pydantic models.
- **Declarative Visualization (`ChartSpec`)** — `vega-lite` (preferred) or `plotly-json` chart payloads validated at server-side. Replaces LLM-generated Python `exec()` chart code.
- **Read-only SQL enforcement** — `RunSqlTool` defaults to read-only statement classes; write SQL raises a validation error.
- **User-Aware Agent** — `User`, `UserResolver`, `RequestContext` — identity, group memberships, and row-level security flow through every tool call.
- **Tool Permission System** — `Tool.access_groups` RBAC enforced by `ToolRegistry._validate_tool_permissions`.
- **Lifecycle Hooks** — `request_guard`, `on_query_start`, `on_query_end` hook points for quota, rate limiting, and audit logging.
- **LLM Middlewares** — Caching and prompt engineering middleware chain around LLM calls.
- **Lineage & Evidence collector** — Every answer carries schema snapshot ID, retrieved memories, tool call durations, executed SQL, and tiered confidence (`High / Medium / Low`).
- **v3 Flask + FastAPI routes** — Namespaced under configurable `api_v3_prefix` (default `/api/vanna/v3`).
- **`<vanna-chat>` web component** (`frontends/webcomponent/`) — Drop-in SSE-native chat component with table, chart, and summary rendering. Supports dark/light themes and is framework-agnostic.
- **LLM Integrations** — Anthropic, OpenAI, OpenRouter, Google Gemini, Azure OpenAI, Ollama — all with Tox integration test environments.
- **Database runners** — PostgreSQL, MySQL, SQLite, DuckDB, Snowflake, BigQuery, ClickHouse, Oracle, SQL Server (via pyproject extras).
- **`LegacyVannaAdapter`** — Smooth bridge from upstream v2 interface to v3 internals; all `ask()` / `generate_sql()` methods preserved.
- **Migration guide** (`docs/v3/migration-v2-to-v3.md`, `MIGRATION_GUIDE.md`).
- **Threat model** (`docs/v3/threat-model.md`) — Documents prompt injection, data exfiltration, unauthorized skill promotion, PII risks, and session memory leakage with mitigations.

### Security

- CORS defaults: no wildcard `allow_origins`.
- Auth middleware hook points — JWT/OAuth gateway handoff templates.
- Legacy Python chart execution (`exec()`) disabled by default; opt-in via `allow_unsafe_plotly_code_execution: True` (admin-only environments).
- All unauthenticated endpoints removed from default routes.

### Deprecated

- `POST /api/vanna/v2/chat_sse` — Still available for backward compatibility but superseded by `/api/vanna/v3/chat/events`.
- LLM-generated Plotly code execution — Replaced by `ChartSpec`. Legacy behavior available behind opt-in flag.

---

## Upstream Baseline

This fork starts from **vanna-ai/vanna v2.0** (the upstream OSS release). The upstream project is maintained at [github.com/vanna-ai/vanna](https://github.com/vanna-ai/vanna).
