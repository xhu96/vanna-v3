# Vanna v3 Golden Path Examples

- `fastapi_jwt_postgres.py`: FastAPI + JWT + Postgres + v3 routes.
- `trusted_oauth_gateway.py`: private-network, signed identity-header pattern for
  an OAuth gateway that strips all client-supplied identity headers.
- `multi_tenant_rls.py`: Verified token groups/tenant plus query-layer RLS;
  caller-controlled tenant headers are intentionally ignored.
- `semantic_adapter_demo.py`: Runnable offline semantic-first example using the
  file adapter and read-only SQLite.
- `dbt_semantic_layer.py`: Golden dbt Semantic Layer adapter wiring with an
  injected HTTP client and environment-supplied token.
- `schema_sync_cron.py`: Tenant-scoped schema sync using the application's
  durable memory implementation and an explicit trusted table allowlist;
  includes the standalone CLI command. `INFORMATION_SCHEMA` deployments use
  `--include-schema`, while SQLite uses `--include-table`.
- `byo_ui_event_stream.py`: Framed custom SSE client with V3 version/type,
  unique ID, contiguous sequence, stable request/conversation ID, exactly-one
  lineage, and terminal validation. Browser clients can import
  `VannaApiClient` and call `streamV3Events` without mounting the bundled UI.

Approved feedback is exported and evaluated offline; CI regression checks do
not promote candidates:

```bash
python src/evals/pipelines/export_approved_feedback.py \
  --database .vanna/feedback.sqlite3 --tenant-id acme \
  --out artifacts/acme-approved.jsonl
python src/evals/pipelines/run_offline_eval.py \
  --candidate-factory vanna.evals.candidates.sqlite_policy:build_variant \
  --approved-feedback-manifest artifacts/acme-approved.jsonl.manifest.json \
  --approved-feedback artifacts/acme-approved.jsonl \
  --out artifacts/candidate-metrics.json
python src/evals/pipelines/offline_training_gate.py \
  --baseline src/evals/baselines/sql_generation.json \
  --candidate artifacts/candidate-metrics.json \
  --candidate-factory vanna.evals.candidates.sqlite_policy:build_variant \
  --approved-feedback artifacts/acme-approved.jsonl \
  --expected-candidate v3-sqlite-policy-stack \
  --mode promote
```

Promotion reruns the exact supplied candidate factory and dataset. It fails when
the recorded metrics differ from that execution, the export contains no approved
record, the JSONL bytes no longer match the manifest, any fixed slice regresses,
or the candidate does not improve a fixed aggregate quality metric. CI uses the
same checked candidate in `--mode check` and never promotes an artifact.
