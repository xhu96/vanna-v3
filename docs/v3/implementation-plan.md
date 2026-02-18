# Vanna v3.0 Implementation Plan

## Delivery Strategy
- Incremental rollout via v3 modules + feature flags.
- Preserve v2 behavior behind compatibility adapters/routes.
- Every phase lands with tests and docs updates.

## Milestones and Commit Groups

### M1: v3 Contract + Security Baseline
Deliverables:
- Typed v3 streaming event envelope.
- Safe CORS defaults + auth/rate-limit middleware hook points.
- Read-only SQL enforcement default.
- Disable legacy Python-chart execution by default.

Planned file-level changes:
- `src/vanna/servers/base/models.py` (v3 event models + compatibility mapping)
- `src/vanna/servers/fastapi/routes.py` (v3 event endpoint)
- `src/vanna/servers/flask/routes.py` (v3 event endpoint)
- `src/vanna/servers/fastapi/app.py` (safe defaults + middleware hooks)
- `src/vanna/servers/flask/app.py` (safe defaults + middleware hooks)
- `src/vanna/tools/run_sql.py` (read-only query validator)
- `src/vanna/legacy/base/base.py` (secure chart default + explicit opt-in)
- `tests/test_tool_permissions.py`, `tests/test_database_sanity.py` (+ security tests)

### M2: Declarative Visualization Protocol
Deliverables:
- ChartSpec schema (`vega-lite` preferred, `plotly-json` optional).
- Visualization tool emits ChartSpec + dataset payload.
- Frontend renders declarative specs.

Planned file-level changes:
- `src/vanna/components/rich/data/chart.py` (chart spec payload fields)
- `src/vanna/tools/visualize_data.py` (emit validated ChartSpec)
- `src/vanna/core/validation.py` (ChartSpec validators)
- `frontends/webcomponent/src/components/rich-component-system.ts` (ChartSpec rendering path)
- `frontends/webcomponent/src/components/plotly-chart.ts` (plotly-json compatibility path)
- `tests/test_chart_spec_validation.py` (new)
- `tests/test_visualization_tool.py` (new)

### M3: Schema Catalog + Drift Sync
Deliverables:
- Cross-DB snapshot ingestion via catalog queries.
- Schema hash/version + diffing.
- Scheduler (cron-compatible) + on-demand sync endpoint.
- Drift metadata surfaced to lineage.

Planned file-level changes:
- `src/vanna/capabilities/schema_catalog/base.py` (new interface)
- `src/vanna/capabilities/schema_catalog/models.py` (snapshot/diff models)
- `src/vanna/integrations/schema_catalog/sql_catalog.py` (portable SQL-based snapshotter)
- `src/vanna/services/schema_sync.py` (sync service + scheduler)
- `src/vanna/servers/fastapi/routes.py` / `src/vanna/servers/flask/routes.py` (sync endpoints)
- `tests/test_schema_diff.py` (new)
- `tests/test_schema_sync_service.py` (new)

### M4: Semantic-First Planning + Adapter
Deliverables:
- `SemanticTool` interface + query model.
- Golden adapter (MetricFlow/dbt-compatible HTTP adapter or mockable adapter).
- Planner prefers semantic path and warns on SQL fallback.

Planned file-level changes:
- `src/vanna/capabilities/semantic/base.py` (new)
- `src/vanna/capabilities/semantic/models.py` (new)
- `src/vanna/tools/semantic_query.py` (new)
- `src/vanna/core/planner/semantic_first.py` (new)
- `src/vanna/core/agent/agent.py` (planner integration and warning emission)
- `tests/test_semantic_planner.py` (new)

### M5: Explainability + Lineage
Deliverables:
- Lineage capture for every answer.
- Evidence includes schema hash, memories, tool calls, SQL, runtime, checks.
- Tiered confidence derived from explicit rules/signals.

Planned file-level changes:
- `src/vanna/core/lineage/models.py` (new)
- `src/vanna/core/lineage/collector.py` (new)
- `src/vanna/core/lineage/confidence.py` (new)
- `src/vanna/core/registry.py` (tool call lineage hooks)
- `src/vanna/core/agent/agent.py` (emit lineage event/component at completion)
- `tests/test_lineage_capture.py` (new)

### M6: Feedback Loop + Eval-Gated Offline Training
Deliverables:
- Feedback endpoint + corrected SQL/reason-code capture.
- Immediate memory patching (positive/negative/corrective, weighted).
- Optional review queue for golden memories.
- Offline training pipeline gated by eval improvements.

Planned file-level changes:
- `src/vanna/services/feedback/models.py` (new)
- `src/vanna/services/feedback/store.py` (new)
- `src/vanna/services/feedback/patcher.py` (new)
- `src/vanna/servers/fastapi/routes.py` / `src/vanna/servers/flask/routes.py` (feedback endpoint)
- `src/evals/pipelines/offline_training_gate.py` (new)
- `tests/test_feedback_memory_patching.py` (new)

### M7: CI Reliability Gates + Integration Coverage
Deliverables:
- Add integration suite with dockerized Postgres + mocked semantic adapter.
- Add security tests for non-reachable Python exec-by-default and ChartSpec hard validation.
- Eval regression check in CI.

Planned file-level changes:
- `.github/workflows/tests.yml` (eval + integration jobs)
- `tox.ini` (new envs: integration/eval/security)
- `tests/integration/test_postgres_v3_pipeline.py` (new)
- `tests/security/test_secure_defaults.py` (new)
- `tests/security/test_chart_spec_security.py` (new)

### M8: Docs, Examples, Migration
Deliverables:
- Golden path examples:
  - FastAPI + JWT + Postgres
  - Multi-tenant groups + RLS
  - Semantic layer example
  - BYO UI event stream consumption
- Migration guide v2 -> v3 + compatibility adapter guidance.

Planned file-level changes:
- `docs/v3/migration-v2-to-v3.md` (new)
- `docs/v3/api-events-v3.md` (new)
- `examples/v3/fastapi_jwt_postgres.py` (new)
- `examples/v3/multi_tenant_rls.py` (new)
- `examples/v3/semantic_adapter_demo.py` (new)
- `examples/v3/byo_ui_event_stream.py` (new)

## Quality Gates
- Unit tests for each milestone’s new logic.
- Integration tests include one real DB backend (dockerized Postgres).
- Security tests required for secure defaults and visualization constraints.
- CI fails on eval regression relative to baseline dataset.

