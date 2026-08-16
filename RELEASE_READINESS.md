# Vanna 3.3.0 Release Readiness

Status date: 2026-08-16

## Disposition

The source tree passes the deterministic local and GitHub CI gates listed below. Automated package publication remains disabled. A source update on GitHub does not publish Python or npm artifacts, create a release, or move an existing tag.

## Version Lineage

Public repository tags `v3.1.0` and `v3.2.0` already exist, so the next package version is `3.3.0`; `3.0.0` must not be reused. The tagged `v3.2.0` commit is on a divergent branch rather than in this candidate's ancestry. Maintainers must reconcile that line before publishing packages or creating a `v3.3.0` tag. Existing tags remain immutable.

The wire protocol remains version `v3`. Package version `3.3.0` does not require new route names or event-envelope versions.

## Delivered Scope

- Strictly validated declarative Vega-Lite and Plotly chart specifications.
- Static sanitized artifacts with no executable chart or artifact mode.
- Dialect-aware read-only SQL policy, recursive tenant filtering, and native read-only runner enforcement.
- Production authentication, route authorization, safe CORS/UI defaults, rate-limit hooks, stable public errors, and conversation ownership.
- Backward-compatible V2 SSE, poll, and FastAPI WebSocket contracts, with V3 typed SSE and poll as an explicit client option.
- Portable tenant-scoped schema snapshots, immutable history, drift diffs, memory updates, on-demand sync, and cron-compatible execution.
- dbt Semantic Layer GraphQL adapter and deterministic semantic-first routing.
- Structured lineage and signal-derived High/Medium/Low confidence.
- Tenant-scoped corrective feedback, durable review state, approved-only export, and an evaluation-gated promotion pipeline.
- FastAPI, OAuth gateway, PostgreSQL/JWT, multi-tenant filtering, dbt, schema scheduling, and custom event-stream examples.
- Lit and Adobe Spectrum web component with locally bundled fonts, typed V3 transport, and responsive evidence UI.

## Latest Local Verification

| Gate | Result |
|---|---|
| Python offline inventory | 694 passed, 2 optional dependency skips, 1 third-party deprecation warning |
| Test inventory ownership | 4 passed |
| Ruff | Format and lint passed across 300 files |
| Strict mypy | 125 source files passed |
| Frontend unit tests | 75 passed across 8 files |
| Chromium interaction and security tests | 5 passed |
| Frontend production build | Passed with package version `3.3.0` |
| Storybook build | Passed |
| npm dependency audit | 0 vulnerabilities across production and development dependencies |
| Runtime policy | Python 3.11 minimum; Node 20.19.x and npm 10 verified |
| Source-tree integrity | Diff whitespace, local links, generated-file exclusions, and public metadata checks passed |

The Storybook build reports its own development-runtime `eval` use and large Plotly/Vega preview chunks. Neither path introduces model-generated code execution; production chart payloads remain declarative and policy-validated. Bundle splitting remains a separate performance optimization.

## Latest GitHub Verification

[GitHub Actions run 31964163758](https://github.com/xhu96/vanna-v3/actions/runs/31964163758) passed on the uploaded `main` head:

| Job | Result |
|---|---|
| Complete Python 3.11 gate | Passed |
| Python package matrix | 3.11, 3.12, 3.13, and 3.14 passed |
| PostgreSQL 15 integration | Passed with the read-only, multi-tenant reference flow |
| Offline evaluation gate | Passed |
| Frontend unit, deterministic build, Storybook, and Chromium tests | Passed |

GitHub-maintained actions are pinned to immutable Node 24 release commits. The run completed without the previous action-runtime deprecation annotations.

## External Release Gates

The following still require release-owner or deployment evidence before package publication:

- Wheel/sdist reproducibility, Twine validation, and clean-wheel installation.
- Live dbt tenant compatibility and bounded semantic-query polling.
- Deployment performance budgets, proxy buffering/cancellation, and lineage overhead against the reference PostgreSQL flow.
- Reconciliation of the divergent `v3.2.0` line and package namespace approval.

The GitHub Actions workflows define the PostgreSQL, Python matrix, frontend, evaluation, and artifact-verification jobs. Publishing credentials and package-upload steps are intentionally absent.

## Release Rule

Do not publish packages solely because the local suite passes. Publication requires all external gates, exact package/version equality across Python and npm metadata, immutable artifacts, and explicit release-owner approval.
