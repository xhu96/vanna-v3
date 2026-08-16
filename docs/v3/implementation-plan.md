# Vanna 3.3.0 Implementation Plan

Status date: 2026-08-12

This release incrementally extends the V2 agent architecture. V2 routes and
frontend behavior remain the default; V3 capabilities use explicit, versioned
contracts. Each feature has direct regression coverage and release-facing
operational documentation.

## Milestones

| Milestone | Status | Primary modules |
|---|---|---|
| Architecture and contracts | Complete | `docs/v3/`, event and ChartSpec JSON schemas |
| Reproducible test harness | Complete offline | `tests/test_inventory.toml`, `tox.ini`, CI workflows, frontend Vitest/Playwright |
| Secure execution boundaries | Complete offline | `src/vanna/security/`, SQL tools/runners, server security, static renderers |
| Typed API and frontend transport | Complete offline | V3 event models, FastAPI/Flask routes, SSE parser, web component protocol adapter |
| Schema drift | Complete offline | catalog adapters, transactional snapshot store, sync service/CLI |
| Semantic-first routing | Complete offline | semantic planner, dbt GraphQL adapter, file adapter policy executor |
| Lineage and confidence | Complete offline | lineage models/collector, agent finalization, permission filtering |
| Feedback and evaluation | Complete offline | feedback service/store, memory ranking, approved export, eval promotion gate |
| Packaging and release | Implemented; external gates pending | Python/npm metadata, build-only workflow, release readiness report |

## File-Level Mapping

### API and Security

- `src/vanna/servers/base/events_v3.py`: discriminated events, sequence and
  terminal state machine, poll response validation.
- `src/vanna/servers/base/security.py`: production startup requirements and
  prohibited capability checks.
- `src/vanna/servers/fastapi/` and `src/vanna/servers/flask/`: namespaced routes,
  authentication, authorization, rate limiting, error redaction, and parity.
- `src/vanna/security/sql_policy.py` and `src/vanna/security/rls.py`: AST
  read-only validation and recursive tenant policy.
- `src/vanna/tools/run_sql.py`: model-facing SQL policy and result limits.

### Visualization and Frontend

- `src/vanna/core/chart_spec.py`: closed safe profiles and dataset limits.
- `src/vanna/tools/visualize_data.py`: declarative chart generation only.
- `frontends/webcomponent/src/services/api-client.ts`: V2/V3 SSE and poll.
- `frontends/webcomponent/src/types/events-v3.ts`: typed envelope validation.
- `frontends/webcomponent/src/security/`: sanitized rendering boundaries.

### Schema and Semantics

- `src/vanna/integrations/schema_catalog/`: SQLite and Information Schema
  discovery with trusted source scopes.
- `src/vanna/capabilities/schema_catalog/store.py`: tenant-scoped immutable
  snapshots and durable scheduling state.
- `src/vanna/services/schema_sync.py`: diffing, versioning, memory outbox, and
  idempotent sync.
- `src/vanna/integrations/semantic/dbt_adapter.py`: tenant-bound bounded dbt
  GraphQL metadata/query execution.
- `src/vanna/core/planner/semantic_first.py`: deterministic semantic coverage
  and SQL fallback policy.

### Lineage, Feedback, and Evaluation

- `src/vanna/core/lineage/`: serializable evidence and signal-derived confidence.
- `src/vanna/core/agent/agent.py`: lineage finalization on all accepted paths.
- `src/vanna/services/feedback.py` and `feedback_store.py`: immediate memory
  updates, ownership, durable review state, and approved records.
- `src/evals/`: fixed datasets, candidate execution, approved-data provenance,
  aggregate/slice regression checks, and promotion mode.

## Verification Matrix

| Area | Required scenarios |
|---|---|
| SQL and tenant policy | Mutations, stacked statements, write CTEs, vendor commands, PRAGMAs, nested sources, joins, aliases, subqueries, unions, semantic execution, native read-only enforcement |
| API | V2 fixtures, V3 schema and framing, empty/error streams, terminal ordering, poll parity, custom prefixes, auth failures, cancellation, WebSocket credential refresh and ownership |
| Frontend | Fragmented SSE, protocol selection, no replay, V2 timeout compatibility, ChartSpec rejection, static artifacts, CSP/browser isolation |
| Schema | SQLite/Information Schema discovery, stable hashes, versions, all diff types, atomic writes, tenant isolation, history, scheduler idempotency |
| Semantic | Catalog pagination, filters, grains, ordering, redirects, response limits, timeouts, service errors, full/partial/missing coverage |
| Lineage | Normal, zero-row, semantic, fallback, shortcut, tool-limit, and error paths; redaction and confidence rules |
| Feedback/eval | Correction, suppression, tenant isolation, review ordering, approved-only export, immediate retrieval, candidate identity, malformed metrics, aggregate/slice regressions |
| Packaging | Python 3.11-3.14, metadata equality, two builds, Twine, clean install, CLI/SQLite smoke, MIT contents, frontend build/test/Storybook |
| Integration | PostgreSQL 15 read-only role, two tenants, drift, mocked dbt, table/chart/lineage, feedback correction on next request |

## Remaining Release Work

- Reconcile the divergent public `v3.2.0` line before publishing `v3.3.0`.
- Run package artifacts and the supported Python matrix in CI.
- Run PostgreSQL 15 with a least-privilege role and two tenants.
- Validate one bounded query against the target dbt tenant.
- Measure live proxy behavior and documented performance budgets.
- Keep all publication steps disabled until release-owner approval.
