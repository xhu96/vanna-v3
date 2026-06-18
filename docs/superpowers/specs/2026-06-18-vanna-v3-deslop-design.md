# vanna-v3 De-Slop & Hardening — Design Spec

**Date:** 2026-06-18
**Author:** Xhulio Lavdari (xhu96)
**Branch:** `cleanup/v3-deslop`
**Status:** Approved (design); pending implementation plan

## Context

`vanna-v3` is an unofficial "v3" community fork of [vanna-ai/vanna](https://github.com/vanna-ai/vanna),
built on upstream `v2.0.2`. A prior audit found the v3 additions to be real, tested code but with the
hallmarks of an AI-generated scaffold ("slop"): a flagship "secure-by-default" claim with real holes,
features that are mocks/stubs presented as working, decorative CI, inconsistent release metadata, and
~11k LOC of inherited `legacy/` code carrying two unpatched SQL-injection CVEs.

This effort cleans and hardens the v3 work so the code matches its claims, the stubbed features become
real, and the dead inherited surface (incl. the CVEs) is removed.

### Baseline (verified 2026-06-18)
- Local clone builds: `python -m venv .venv && pip install -e '.[test]'` succeeds on Python 3.14.
- `274` tests collect; the `17` v3-specific tests pass. This is the green baseline to preserve.
- No runtime (non-legacy, non-test) module imports `vanna.legacy`. `legacy/` is referenced only by
  tests, docs, and `__init__` re-exports — it is a standalone, effectively-unused subsystem.
- Version slop: `__version__ = "0.1.0"` (code) vs `version = "2.0.2"` (pyproject) vs `v3.x` git tags.

## Goals
1. Make "secure-by-default" literally true (no exploitable read-only bypass; no injection in examples).
2. Turn the three stubbed features into real, working implementations.
3. Delete the unused `legacy/` subsystem, eliminating CVE-2026-4513 / CVE-2026-4229 exposure.
4. Remove AI-slop: dead code, false abstraction, fragile async, committed artifacts, overclaiming docs.
5. Unify versioning and ship the result as a reviewable PR.

## Non-Goals
- No new product features beyond making existing claims real.
- No change to the upstream/inherited integration adapters that v3 actually uses (LLM/DB/vector backends).
- No attempt to revive the project commercially or re-publish to PyPI as part of this work (version is
  unified to `3.0.0` for internal honesty, but releasing is out of scope).

## Guardrails
- **TDD**: each fix/feature begins with a failing test, then implementation. Add negative/edge tests.
- **Always green**: the full non-integration suite stays green after every workstream.
- **Branch → PR**: all work on `cleanup/v3-deslop`; `main` untouched until the user merges. At the end,
  unarchive the repo, push, open a PR.
- **Honest docs**: README/architecture describe only what the code does; illustrative bits are labeled.

## Workstreams

### A. Security correctness
- **A1. Harden read-only SQL validation** (`src/vanna/tools/run_sql.py`): parse with `sqlglot` (AST),
  not first-keyword matching. Reject: data-modifying CTEs (`WITH … DELETE/UPDATE/INSERT/MERGE`),
  multiple statements, and DDL/DML even when comment-prefixed. Keep the read-only allowlist semantics
  (`SELECT/WITH(read-only)/SHOW/DESCRIBE/EXPLAIN/PRAGMA`).
  - Tests: CTE-write is blocked; stacked statement is blocked; legitimate `WITH … SELECT` passes.
- **A2. Enforce read-only at the connection/transaction layer**: where the driver supports it, open the
  runner connection read-only (e.g. Postgres `SET TRANSACTION READ ONLY` / read-only session), so paths
  that bypass `RunSqlTool` (e.g. `schema_sync` calling the runner directly) cannot mutate data.
  - Tests: a runner configured read-only refuses a write issued directly (not via the tool).
- **A3. Fix the RLS example** (`examples/v3/multi_tenant_rls.py`): inject the tenant predicate via AST
  (`sqlglot`) or bound parameters; delete the `f"… tenant_id = '{tenant_id}'"` interpolation and the
  naive `" where " in sql.lower()` detection.
  - Tests: tenant filter applied correctly across `GROUP BY`/subquery/`HAVING`; a malicious `tenant_id`
    cannot break out.
- **A4. Remove the dead non-SELECT result branch** in `run_sql.py` under the read-only default.

### B. Build the stubs for real
- **B1. Real semantic adapter** (`src/vanna/integrations/semantic/`): ship `FileSemanticAdapter` —
  metrics/dimensions/synonyms from a config file (YAML), real term→metric matching, real
  `full/partial/none` coverage, governed SQL/structured-query generation. Move `MockSemanticAdapter` to
  a labeled test fixture under `tests/`. The `SemanticAdapter` interface stays so other backends (Cube,
  dbt) can be added later, but a *real* concrete impl ships now.
  - Tests: full-coverage query routes to semantic + emits expected SQL; uncovered query → `none` → SQL
    fallback; partial coverage handled.
- **B2. Real eval gate** (`src/evals/`): `offline_training_gate` runs the agent over
  `src/evals/datasets/sql_generation/basic.yaml` with a deterministic mock LLM, computes real
  `pass_rate`/`average_score`, and emits the JSON the gate consumes. CI runs the real eval and gates on
  it; delete the hardcoded `baseline.json`/`candidate.json` heredocs in `.github/workflows/tests.yml`.
  - Tests: the runner produces a deterministic score on the dataset; gate fails on a seeded regression.
- **B3. Weight-aware memory retrieval**: ranking in the agent-memory base + in-memory impl
  (`src/vanna/integrations/local/agent_memory/in_memory.py`) factors the `weight` written by
  `services/feedback.py` (negative `2.0`, corrective `5.0`) into the ranking, so corrections actually
  reshape retrieval.
  - Tests: after a thumbs-down + corrected SQL, the corrected example outranks the original for a
    similar question.

### C. Delete unused legacy cruft (decision: L1 — delete entirely)
- Remove `src/vanna/legacy/` in full (~11k LOC), including the files hosting CVE-2026-4513
  (`legacy/base/base.py`) and CVE-2026-4229 (`legacy/google/bigquery_vector.py`).
- Remove dependent tests: `tests/test_legacy_adapter.py`, `tests/test_legacy_chart_security.py`, and the
  legacy import checks in `tests/test_database_sanity.py`; drop the `legacy` pytest marker.
- Remove `LegacyVannaAdapter`/legacy re-exports from `src/vanna/__init__.py` and the legacy sections of
  `MIGRATION_GUIDE.md` / `CONTRIBUTING.md` / `README_LEGACY.md`.
- Rationale: no runtime code imports it; it's an unused migration path on an archived fork; deleting it
  is the largest single de-slop win and removes both CVEs. The no-exec-chart fix becomes moot because
  the live v3 path uses declarative `ChartSpec` and never executes LLM-generated Python.

### D. De-slop & consistency
- **D1. Fix Flask async**: replace per-request `asyncio.new_event_loop()/run_until_complete()/close()`
  in the Flask v3 routes with `asgiref.async_to_sync` (or a single managed loop).
- **D2. Collapse false abstraction**: where a capability is only `base.py` + `models.py` + `__init__.py`
  wrapping a single (now-real) impl, simplify without breaking the public interface.
- **D3. Confidence scoring**: make `ConfidenceScorer` meaningful or rename/document it explicitly as a
  coarse heuristic — no false precision in the lineage card.
- **D4. Remove committed artifacts**: delete `37a8eec1ce19687d/` and `e606e38b0d8c19b2/`
  `query_results_*.csv` dirs; add a `.gitignore` rule for generated query-result files.

### E. Docs & release honesty
- **E1. Rewrite README + `docs/v3/*`** to match the shipped behavior; label any illustrative content.
- **E2. Unify version to `3.0.0`** across `pyproject.toml` and `src/vanna/__init__.__version__`.
- **E3. Update `MIGRATION_GUIDE.md`/`CONTRIBUTING.md`** to reflect the legacy removal.

### F. Delivery
- Reviewable commits, one logical group per workstream (C → A → B → D → E).
- Final step: unarchive `xhu96/vanna-v3`, push `cleanup/v3-deslop`, open a PR summarizing the security
  rationale, the now-real features, the legacy/CVE removal, and the real eval numbers.

## Sequencing & verification
Order: **C → A → B → D → E → F**. Delete the dead surface first (smaller blast radius), then harden,
then build features, then polish, then docs, then ship. Gate every step on:
`python -m pytest -m "not integration"` green + `ruff` + `mypy` clean (the repo already runs these in CI).

## Risks
- Deleting `legacy/` may break re-exports/imports elsewhere — mitigated by the verified "no runtime
  importers" finding and a full test run after deletion.
- `sqlglot` is a new dependency — added to `pyproject` core deps; dialect-aware parsing must default
  safely (parse failure ⇒ reject in read-only mode).
- Read-only-at-connection support varies by driver — applied where supported; the AST guard (A1) is the
  portable backstop.
- Real eval must be deterministic in CI — use a fixed mock LLM and a frozen dataset, no network.

## Success criteria
- All claims in the README are backed by working code; no mocks presented as features.
- Read-only SQL cannot be bypassed by CTE-writes, stacked statements, or direct-runner paths.
- The RLS example contains no string-interpolated SQL.
- `legacy/` is gone; `pip-audit`/grep shows no CVE-2026-4513/4229 code paths remain.
- The eval gate runs a real evaluation in CI on real numbers.
- One coherent version (`3.0.0`); full non-integration suite green; `ruff`/`mypy` clean.
