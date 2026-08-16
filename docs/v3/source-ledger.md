# Vanna V3 Primary Source Ledger

Baseline access date: 2026-08-08. Later additions carry their own access date.
Sources are primary specifications or vendor/project documentation. The ledger
records the external contract used by the design; it does not authorize an
unreviewed dependency upgrade.

| Area | Version/scope | Primary source | Design use |
|---|---|---|---|
| Server-Sent Events | WHATWG HTML Living Standard, section 9.2; developer edition updated 2026-07-16 | [Server-sent events](https://html.spec.whatwg.org/dev/server-sent-events.html) and [normative event-stream parsing](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream) | UTF-8 stream, blank-line dispatch, `event`, `data`, `id`, multiline data, and LF/CRLF/CR handling |
| HTML sandboxing | WHATWG HTML Living Standard | [The iframe element and sandbox attribute](https://html.spec.whatwg.org/multipage/iframe-embed-object.html#attr-iframe-sandbox) | Static artifact iframe uses an empty sandbox; no script/same-origin escape combination |
| PostgreSQL catalogs | PostgreSQL 15 | [Information Schema](https://www.postgresql.org/docs/15/information-schema.html), [columns](https://www.postgresql.org/docs/15/infoschema-columns.html), and [tables](https://www.postgresql.org/docs/15/infoschema-tables.html) | Portable first-pass catalog snapshots and visibility semantics |
| PostgreSQL read-only execution | PostgreSQL 15 | [START TRANSACTION](https://www.postgresql.org/docs/15/sql-start-transaction.html) and [SET TRANSACTION](https://www.postgresql.org/docs/15/sql-set-transaction.html) | Start a transaction with `READ ONLY`; DB role remains the stronger control |
| SQLite catalog and PRAGMAs | SQLite current docs, PRAGMA page updated 2026-06-04 | [PRAGMA statements](https://www.sqlite.org/pragma.html), [schema table](https://www.sqlite.org/schematab.html), and [URI filenames](https://www.sqlite.org/uri.html) | `table_list`/`table_xinfo`, explicit informational PRAGMA allowlist, `query_only`, `trusted_schema`, and URI `mode=ro` |
| dbt Semantic Layer | dbt Semantic Layer GraphQL, page updated 2026-08-06 | [GraphQL API](https://docs.getdbt.com/docs/dbt-apis/sl-graphql) | Metadata pagination, metrics, dimensions, grains, create-query, ordering, polling, result pagination, and auth requirements |
| Vega-Lite | Safe profile pinned to Vega-Lite V5 | [V5 JSON Schema](https://vega.github.io/schema/vega-lite/v5.json), [view specification](https://vega.github.io/vega-lite/docs/spec.html), and [data sources](https://vega.github.io/vega-lite/docs/data.html) | V5 single-view declarative subset; full grammar has external data/transforms and is intentionally narrowed |
| Python package metadata | PyPA specifications accessed 2026-08-08 | [`pyproject.toml` specification](https://packaging.python.org/specifications/declaring-project-metadata/), [core metadata](https://packaging.python.org/en/latest/specifications/core-metadata/), and [writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) | `requires-python`, static version/name, extras, project URLs, and license metadata |
| GitHub Actions | GitHub Actions docs accessed 2026-08-08 | [Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts), and [store/share artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data) | Minimal permissions, immutable build artifacts, digest/provenance evidence, and build-only release verification |
| FastAPI CORS/security integration | FastAPI docs; baseline package 0.141.1 | [CORS](https://fastapi.tiangolo.com/tutorial/cors/), [middleware](https://fastapi.tiangolo.com/tutorial/middleware/), and [security](https://fastapi.tiangolo.com/tutorial/security/) | Explicit origins, middleware placement, authentication templates, and route integration |
| Flask security integration | Flask 3.1.x docs; baseline package 3.1.3 | [Security considerations](https://flask.palletsprojects.com/en/stable/web-security/), [lifecycle](https://flask.palletsprojects.com/en/stable/lifecycle/), and [error handling](https://flask.palletsprojects.com/en/stable/errorhandling/) | Application setup order, security headers guidance, and stable public error handlers |
| SQL parsing | sqlglot API; baseline package 30.15.0, project minimum initially 25 | [sqlglot API](https://sqlglot.com/sqlglot.html), [AST expressions](https://sqlglot.com/sqlglot/expressions.html), and [project README](https://github.com/tobymao/sqlglot) | Explicit dialect parsing, AST traversal, identifier qualification, and fail-closed parse errors |
| JSON Schema | Draft 2020-12 | [JSON Schema 2020-12 specification](https://json-schema.org/draft/2020-12/json-schema-core.html) | Versioned discriminated event and ChartSpec schemas with unknown fields rejected |
| Spectrum Web Components | 1.12.2, accessed 2026-08-16 | [Official component documentation](https://opensource.adobe.com/spectrum-web-components/), [theme contract](https://opensource.adobe.com/spectrum-web-components/tools/theme/), and [Adobe repository](https://github.com/adobe/spectrum-web-components) | Lit-native Spectrum 2 theme, text field, button, action button, and progress primitives; locally bundled with no runtime CDN |
| IBM Plex via Fontsource | Fontsource packages 5.3.0, accessed 2026-08-16 | [`@fontsource-variable/ibm-plex-sans`](https://www.npmjs.com/package/@fontsource-variable/ibm-plex-sans) and [`@fontsource/ibm-plex-mono`](https://www.npmjs.com/package/@fontsource/ibm-plex-mono) | Locally bundled OFL-1.1 UI and mono fonts; no remote font request |

## Source-Control Rules

- Runtime behavior is tested against the versions resolved by the committed
  Python/npm metadata and lockfiles, not against a documentation page alone.
- Vendor event hooks, semantic endpoints, and optional DB extensions may
  accelerate a feature but cannot replace the portable/mock contract.
- When a linked living document changes materially, update this ledger and add
  or adjust a conformance test in the same change.
- Do not copy full third-party schemas into runtime code except where their
  license permits it. Vanna's ChartSpec schema is an independently defined safe
  subset, not a redistribution of the full Vega-Lite schema.
