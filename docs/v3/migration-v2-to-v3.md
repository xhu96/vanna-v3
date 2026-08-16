# Migration Guide: Vanna 2.x to Vanna 3.3

Status: migration contract for the 3.3.0 release candidate. V3 is an
incremental layer over the V2 agent architecture, not a big-bang replacement.
Publication remains disabled and the release blockers are listed below.

## Compatibility Summary

| Area | V2 behavior in V3 | Migration action |
|---|---|---|
| Python | V3 supports Python 3.11 and later | Upgrade Python before installing if the V2 deployment uses 3.9 or 3.10 |
| Python/npm names | `vanna` and `@vanna/webcomponent` remain unchanged | Pin and test `3.3.0`; publishing is disabled in this branch |
| Python execution tools | V2 class imports remain, but built-in execution/install tools are inert and production rejects their capability | Remove them from registries; use a separately administered sandbox service outside core V3 |
| V2 SSE/poll | Existing paths and chunk payloads remain | No client change required |
| FastAPI V2 WebSocket | Existing path/payload retained with handshake plus per-message authentication, stable-principal enforcement, atomic supplied-conversation claim, and terminal repairs | Verify credential revocation, foreign-ID denial before agent work, and completion fixture |
| Flask V2 WebSocket | Remains unsupported with explicit `501` | Use V2 SSE/poll or V3 SSE/poll |
| Web component | Defaults to V2 | Set `api-version="v3"` only after adopting typed events |
| Optional bundled UI | Disabled; self-hosted same-origin module only when enabled | Configure `component_script_path` and local static serving, or use a BYO client |
| Default server security | Production mode requires authentication; CORS/UI are off unless configured | Configure a resolver/authorizer and explicit origins/UI |
| SQL | Row policy, AST validation, and a native read-only runner capability are default; production rejects `read_only=False` tools | Use a read-only DB role, trusted tenant policy, and correct dialect |
| Charts | Declarative ChartSpec only | Remove code-generation chart customizations; adopt the safe JSON contract |
| Semantic layer | Semantic-first when an adapter is configured | Configure dbt GraphQL or retain explicit SQL fallback warnings |
| Schema state | Tenant-scoped snapshots and versions | Configure durable snapshot path/store and scheduled sync |
| Lineage | Typed evidence accompanies every accepted answer | Update storage/observability and permission policy |
| Feedback | Authenticated, owner-scoped, durable review state | Configure the feedback store and approval workflow |

## Important Clarifications

- There is no legacy chart "power mode" in core V3. There is no option named
  `allow_unsafe_plotly_code_execution`. Earlier draft guidance describing that
  option was incorrect and has been removed.
- Built-in `RunPythonFileTool` and `PipInstallTool` imports are retained only as
  inert compatibility shims. They never invoke a command service, and production
  startup rejects any registered `arbitrary_code_execution` capability. There is
  no core power-mode switch; integrate legitimate code execution through a
  separately deployed, administrator-controlled sandbox service.
- JavaScript artifacts never execute. HTML artifacts are sanitized static
  content in an empty iframe sandbox.
- The pre-2.0 `VannaBase` compatibility adapter is not restored by this fork.
  Users of Vanna 0.x must first migrate to the V2 agent architecture described
  in the top-level `MIGRATION_GUIDE.md`.
- Public repository tags/releases named `v3.1.0` and `v3.2.0` already exist,
  so `3.0.0` cannot be reused. This candidate uses `3.3.0`, but release owners
  must first reconcile the divergent `v3.2.0` line.

## Step 1: Upgrade the Runtime

V3 requires Python 3.11 or later. A V2 environment on an older interpreter
must create a new environment rather than upgrading in place:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'vanna==3.3.0'
```

The supported CI matrix is Python 3.11 through 3.14. Database drivers may have
narrower platform support; install only the required extras.

## Step 2: Preserve V2 Before Enabling V3

Keep existing V2 endpoint attributes and capture golden fixtures for the
deployment:

```html
<vanna-chat
  api-version="v2"
  sse-endpoint="/api/vanna/v2/chat_sse"
  poll-endpoint="/api/vanna/v2/chat_poll"
  ws-endpoint="/api/vanna/v2/chat_websocket">
</vanna-chat>
```

`api-version` defaults to `v2`, so it can be omitted. Verify:

- existing rich/simple chunk shapes;
- custom API prefixes;
- conversation/request IDs;
- poll and SSE behavior;
- FastAPI WebSocket authentication if used.

Do not switch V2 URLs globally as part of the package upgrade.

Custom `ConversationStore` implementations keep the legacy
`update_conversation()` method for direct V2 compatibility. Production V3
requires atomic ownership enforcement: implement
`update_conversation_for_user(conversation, user)`, return access-denied rather
than missing for a foreign ID, and set `supports_atomic_ownership = True` only
after conflicting-create and foreign-update tests pass. Production also
requires `supports_atomic_updates = True`: concurrent same-owner saves must
append only the messages created from each loaded snapshot rather than replace
one another. The built-in memory and filesystem stores implement both
capabilities, and network chat routes claim ownership before hooks, workflows,
or model calls.

Custom `AgentMemory` implementations remain usable for ordinary V2 memory
operations. Schema drift patching additionally requires tenant-scoped,
idempotent keyed replacement: implement `upsert_text_memory(..., memory_key=)`,
set `supports_keyed_text_memory_upsert = True`, and prove that the same
tenant/key replaces exactly one logical record while another tenant cannot
collide with it. Append-only stores fail closed and leave the durable schema
outbox pending. If an experimental pre-release V3 build already appended schema
patch records, remove those records with the backend's reviewed admin tooling
before the first full sync; V3 does not guess which unkeyed record is current.

Immediate feedback patching has the parallel requirement
`upsert_tool_usage(..., memory_key=...)` plus
`supports_keyed_tool_memory_upsert = True`. A retry with the same tenant and
feedback-derived key must replace exactly one negative/corrective patch.
Append-only tool-memory stores are rejected before feedback is persisted; they
must be upgraded or feedback must remain disabled.

Custom tenant registries that call `apply_row_filter()` remain source
compatible. For production, pass the catalogued `protected_tables` and SQL
`dialect` keyword arguments. Every physical source must match a row policy;
shared dimensions are permitted only through the explicit
`allowed_unfiltered_tables={"dimension_name"}` allowlist. Unknown, ambiguous,
or unmatched sources fail closed.

## Step 3: Configure Production Security

The V3 server factory accepts explicit secure configuration:

```python
server_config = {
    "security_mode": "production",
    "api_v2_prefix": "/api/vanna/v2",
    "api_v3_prefix": "/api/vanna/v3",
    "enable_default_ui_route": False,
    "cors": {"enabled": False},
    "route_authorizer": my_route_authorizer,
    "rate_limiter": my_rate_limiter,  # Optional stricter replacement.
}
```

`my_route_authorizer` implements `RouteAuthorizer`. The authenticated user
resolver should return identity and trusted tenant claims explicitly:

```python
return User(
    id=claims["sub"],
    authenticated=True,
    group_memberships=claims.get("groups", []),
    metadata={"tenant_id": claims["tenant_id"]},
)
```

The built-in anonymous resolver is for explicit loopback development only. Do
not infer identity from an untrusted `X-User-ID` header unless a trusted gateway
removes all client-supplied copies and the resolver validates the gateway.

For model compatibility, `User.authenticated` has a default value. Production
route guards do not trust that default: the resolver must explicitly set the
field, otherwise the request receives `401`. This lets existing non-server V2
code construct `User` while preventing an omitted field from authenticating a
network request.

If no limiter hook is supplied, production installs a principal-scoped fixed
window of 120 requests per minute. Supplying a limiter is therefore an
extension or stricter policy, not the switch that enables throttling.

To enable a cross-origin UI, configure an exact allowlist and only the methods
and headers required by the application:

```python
server_config["cors"] = {
    "enabled": True,
    "allow_origins": ["https://analytics.example.com"],
    "allow_credentials": True,
    "allow_methods": ["POST", "OPTIONS"],
    "allow_headers": ["Authorization", "Content-Type", "Accept"],
}
```

For Flask, use the corresponding `origins` and `supports_credentials` names.
Never combine wildcard or regular-expression origins with credentials; every
credentialed origin must be an exact HTTP(S) origin.

If the optional bundled page is enabled, self-host the built component from the
application origin:

```python
server_config.update(
    {
        "enable_default_ui_route": True,
        "static_folder": "/srv/vanna-ui",  # Contains vanna-components.js.
        "component_script_path": "/static/vanna-components.js",
    }
)
```

Both framework routes require `ui:read` and return the same restrictive CSP,
`nosniff`, frame denial, no-referrer, cross-origin, and permissions headers. The
page has no inline JavaScript, cookie-login demo, remote fonts/runtime, popup,
or artifact listener. The deprecated `cdn_url` setting remains only as a
migration alias for a same-origin absolute path. An external URL, protocol-
relative path, encoded attribute delimiter, dot segment, or query-bearing API
base fails during route registration. BYO clients are unaffected and should
continue to consume the namespaced API directly.

## Step 4: Enforce Database Policy

Use a DB credential that cannot write. Application checks are defense in depth,
not a replacement for grants.

```python
runner = PostgresRunner(
    connection_string=postgres_dsn,
    read_only=True,
)

sql_tool = RunSqlTool(
    sql_runner=runner,
    read_only=True,
    dialect="postgres",
    query_policy=tenant_query_policy,
)
```

The V3 policy parses one statement with the configured dialect, accepts
only read-only query forms, injects recursive alias-qualified tenant filters,
and fails closed unless every physical source matches a row policy or an
explicit `allowed_unfiltered_tables` entry. SQLite uses `mode=ro` and an
explicit informational PRAGMA allowlist.

`SqlQueryPolicy` now requires at least one row policy by default, and
`RunSqlTool` requires `sql_runner.native_read_only is True`. The secure form is:

```python
tenant_query_policy = SqlQueryPolicy(
    "postgres",
    row_policies=trusted_tenant_policy_provider,
    allowed_unfiltered_tables={"calendar_dimension"},
    require_row_policies=True,
)
sql_tool = RunSqlTool(
    sql_runner=runner,
    query_policy=tenant_query_policy,
    require_native_read_only=True,
)
```

For a reviewed single-tenant V2 deployment only, the explicit migration bridge
is `SqlQueryPolicy(..., require_row_policies=False)`. A legacy runner without a
native capability additionally needs `RunSqlTool(...,
require_native_read_only=False)`. These flags are constructor configuration,
never request metadata, and do not disable AST validation. Apply least-privilege
DB grants first and record why the deployment cannot yet use the secure default.

Built-in SQL runners declare their dialect. A custom V2 `SqlRunner` remains
source-compatible, but its inherited `dialect="unknown"` intentionally blocks
default read-only execution. Set a supported `dialect` class attribute or pass
`dialect=...` to `RunSqlTool` after adding dialect-specific policy tests.
SQLite, PostgreSQL, and file-backed DuckDB runners can advertise native
read-only enforcement when configured read-only. Other built-in/custom runners
inherit `native_read_only=False` and are intentionally refused by default until
their driver and credential boundary is certified.

`RunSqlTool(read_only=False)` now declares `privileged_sql_write`. FastAPI and
Flask production factories reject that capability even when the tool is renamed
or access-wrapped. Keep any temporary writable legacy workflow outside the
production model registry and development-only until it is redesigned as an
explicit authorized operation.

The SQLite, PostgreSQL, and DuckDB runners default to `max_result_rows=5000`,
`max_result_bytes=2 * 1024 * 1024`, and `query_timeout_seconds=30`. They fetch
in bounded batches and run blocking driver work outside the event loop.
PostgreSQL sets a transaction-local statement timeout, SQLite installs a
progress-handler deadline, and DuckDB serializes its shared connection while a
timer invokes the driver interrupt and maps timeout diagnostics to a stable
error. None of these paths calls a driver-wide DataFrame materializer before
checking row and byte bounds. `RunSqlTool` reapplies row/byte limits to custom
runner DataFrames before serialization. Configure lower limits for constrained
routes rather than relying on downstream event truncation.

Legacy `SHOW`, `DESCRIBE`, and `EXPLAIN` tool calls are no longer accepted by
the default model-facing query tool because several drivers parse them as
opaque commands. Use the schema catalog APIs for metadata, or expose a separate
admin-authorized diagnostic tool with a dialect-specific allowlist.

Unknown or user-defined SQL functions are denied by default. A deployment that
needs a proven read-only function must pass its normalized name through
`allowed_functions`; built-in dangerous file readers and external scanners
remain denied regardless. `FileSemanticAdapter` and automatic schema catalog
adapters also require a native read-only runner. Their
`require_native_read_only=False` option exists only for the same reviewed
migration bridge.

Existing `apply_row_filter` callers remain supported, but the function now
delegates to the same recursive policy. Move request-derived tenant filters to
the authenticated `ToolContext`; do not accept them from model arguments or
request metadata.

## Step 5: Adopt Typed V3 Events

After V2 parity is green, opt into V3:

```html
<vanna-chat
  api-version="v3"
  protocol="v3"
  sse-endpoint="/api/vanna/v3/chat/events"
  poll-endpoint="/api/vanna/v3/chat/poll">
</vanna-chat>
```

Programmatic configuration uses `protocol: "v3"`:

```typescript
import { VannaApiClient } from '@vanna/webcomponent';

const client = new VannaApiClient({
  protocol: 'v3',
  customHeaders: { Authorization: `Bearer ${token}` },
});

for await (const event of client.streamV3Events({ message: question })) {
  renderKnownEvent(event);
}
```

V3 clients must validate the event envelope, process strictly increasing
sequence numbers, render known payloads only, require exactly one `lineage`
event, require globally unique event IDs, verify a successful
`done.payload.event_count` against the complete sequence, and stop after exactly
one `done` or `error`. See
`docs/v3/api-events-v3.md` and
`docs/v3/schemas/chat-events-v3.schema.json`.

The POST SSE client does not automatically replay through poll after execution
may have started. Expose an explicit retry action and reuse the request ID only
under the server's idempotency policy.

Set `<vanna-chat transport="poll">` or call `sendV3Poll` only when polling is
an explicit integration choice. `cancelCurrentRequest()` aborts the current
chat request without starting another transport.
The configured client timeout remains active until the SSE body completes or
the poll JSON body is parsed; response headers do not cancel the deadline. V3
defaults to 30 seconds. V2 keeps its historical no-implicit-deadline behavior
unless the integration explicitly configures `timeout`.

Chat `metadata` is now a bounded public JSON object: 64 KiB serialized, depth
8, 100 entries per container, 4,096-character strings, 128-character keys, and
finite numbers only. Keys beginning `_vanna_` and schema-lineage keys are
reserved at every depth. Move tenant, authorization, schema lineage, and
internal execution state to the authenticated resolver or server-owned request
context; request metadata cannot select those values.

## Step 6: Migrate Visualization

Delete any custom path that asks an LLM for Python or JavaScript chart code.
Generate or request a `ChartSpec`:

```python
chart = ChartSpec(
    format="vega-lite",
    schema_version="v5-safe-1",
    spec={
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "mark": "bar",
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative"},
        },
    },
    dataset=[{"region": "EMEA", "revenue": 1200.0}],
    metadata={"row_count": 1, "columns": ["region", "revenue"]},
)
```

The safe profile intentionally supports less than the complete Vega-Lite or
Plotly grammar. Unsupported composition, transforms, expressions, config, or
external data must be transformed server-side into the safe subset, not
enabled ad hoc.

## Step 7: Configure Schema Drift

Create a portable catalog service with tenant-scoped durable state and run it
under an admin context:

```python
catalog = PortableSchemaCatalogService(
    sql_runner=runner,
    dialect="postgres",
    persist_path="/var/lib/vanna/schema_catalog.sqlite3",
    cron_schedule="*/15 * * * *",
    catalog_schemas=["analytics"],
)
```

Run from system cron or a worker:

```bash
export VANNA_SCHEMA_DATABASE_URL='postgresql://readonly@db.example/analytics'
export VANNA_SCHEMA_STORE_PATH='/var/lib/vanna/schema_catalog.sqlite3'
python -m vanna.services.schema_sync_cli \
  --tenant acme --include-schema analytics --once
```

Portable discovery is source-scoped separately from tenant snapshot storage.
For `INFORMATION_SCHEMA`, configure `catalog_schemas=[...]` or repeat
`--include-schema`; for SQLite, configure `catalog_tables=[...]` or repeat
`--include-table`. A configured callable may derive the allowlist from trusted
`ToolContext`, and trusted resolver-populated user metadata is the only
fallback. Public chat metadata never widens the catalog query. The explicit
`require_catalog_scope=False` flag exists only to stage a reviewed legacy
single-tenant deployment and should not be used in production.

The standalone CLI is catalog-only: it persists snapshot and outbox state but
does not acknowledge memory patches against temporary memory. Run
`examples/v3/schema_sync_cron.py` inside the application worker with the same
durable `AgentMemory`, or let the next application sync drain the pending
outbox. That memory must implement the keyed-upsert capability described in
Step 2; using an append-only backend is an explicit migration error.

The on-demand endpoint is `POST /api/vanna/v3/schema/sync`; status is
`GET /api/vanna/v3/schema/status`. Both are admin-only by default. A matching
canonical hash is idempotent and does not increment the schema version.

Schema memory entity IDs now percent-encode each schema/table/column component
before dots are used as structural separators. Simple identifiers such as
`public.orders.id` do not change, while literal dots become `%2E`. If a
pre-release V3 deployment wrote unescaped dotted keys, retain the old state for
audit, perform a full tenant-scoped sync into the new store, and verify the
resulting upsert/tombstone set instead of renaming ambiguous keys in place.

The preliminary global `schema_catalog_latest.json` format has no authenticated
tenant provenance and is therefore not imported automatically. Preserve it for
audit, configure a new SQLite store, and only map an old snapshot to a tenant
through an explicit reviewed migration. Pointing the new store at legacy JSON
fails closed with a migration error.

## Step 8: Configure the Semantic Layer

The golden adapter uses dbt Semantic Layer GraphQL with an injected token
provider and HTTP client:

```python
semantic = DbtSemanticLayerAdapter(
    endpoint="https://semantic-layer.example.com/api/graphql",
    environment_id="12345",
    token_provider=lambda context: token_provider(context.user.metadata["tenant_id"]),
    tenant_filter_dimension="tenant_id",
    http_client=http_client,
    query_timeout_seconds=30,
)
```

The adapter requires a resolver-derived tenant value and injects a catalogued
`tenant_id = <resolved tenant>` filter that callers cannot override. The token
provider receives `ToolContext`; use it to select tenant-specific credentials,
or configure a context-bound `environment_id_provider`. Catalog caches are
isolated by environment, tenant-qualified principal, and groups. Missing tenant
claims or protected dimensions fail closed.

Full catalog coverage removes `run_sql` for that turn. Partial or missing
coverage enables SQL and emits a typed fallback warning. An upstream service
failure is terminal by default. Filters are built from catalogued dimensions,
operators, and typed values; user-supplied raw `where` SQL is not accepted.

Use an HTTPS endpoint without embedded credentials, keep redirects disabled on
the injected client, and source tokens from a secret manager through the token
provider. Metadata and result pagination, response bytes, query duration, and
poll attempts are bounded. Public failures contain stable codes and the Vanna
request ID, not dbt responses or credentials.

The adapter is covered by deterministic mocked-HTTP tests. Because this repair
is performed offline and dbt GraphQL availability can vary by account/API
version, run the metadata plus one bounded query probe against the target dbt
tenant before enabling semantic-first routing in production.

Existing `FileSemanticAdapter` remains available for local use, but its SQL is
validated and executed through the shared SQL/RLS policy executor and requires
a native read-only runner unless the reviewed migration bridge is selected.

## Step 9: Persist Lineage and Feedback

Every accepted request emits exactly one permission-filtered lineage event
before its terminal event. An adapter that omits lineage receives a synthetic
Low-confidence failed capture check. Decide which groups can view SQL and
detailed retrieval records, and persist the unredacted internal record according
to tenant retention policy.

Configure a durable feedback store. The local default is transactional SQLite:

```python
feedback = FeedbackService(
    store=SqliteFeedbackStore("/var/lib/vanna/feedback.sqlite3"),
    query_policy=tenant_query_policy,
)
```

A thumbs-down with corrected SQL validates the correction, records ownership
and provenance, suppresses the rejected normalized SQL, and gives the
correction precedence on the next similar retrieval for authorized principals
in the same tenant. Another tenant cannot observe either patch. Only approved review
records can be exported to an offline training candidate.

Pending review records become actionable only after their initial keyed memory
patches are durably marked applied. Review attempts that race a delayed or failed
memory backend fail closed and can be retried after the outbox succeeds; a late
pending write cannot reactivate a rejected correction.

The local exporter publishes owner-only files atomically and writes the
manifest last as the commit marker. Consumers validate the manifest digest
against the exact JSONL bytes, so an interrupted data/manifest pair fails
closed. Use storage with equivalent atomic replacement and durability semantics
for an enterprise exporter.

The reference export endpoint is intentionally bounded to 250 records and
64 MiB. Use a reviewed streaming enterprise exporter for larger approved
datasets. The offline promotion gate requires both the metrics artifact and the
same `--candidate-factory`/dataset used to create it; it executes that stack
again and rejects any mismatch before comparing quality metrics.

## Rollout and Rollback

1. Upgrade Python and package in a staging environment.
2. Run V2 golden fixtures without enabling V3 frontend transport.
3. Enable production security configuration and read-only DB role.
4. Run schema sync and inspect version/hash/lineage.
5. Configure semantic adapter and test full, missing, and outage behavior.
6. Enable V3 for one explicit client cohort.
7. Enable feedback review/export after tenant isolation tests pass.

Rollback keeps V2 routes and sets the frontend back to `api-version="v2"`.
Do not roll back database grants, ownership checks, SQL policy, sanitization, or
error redaction. Schema snapshots and feedback records are additive and should
remain available for audit even when V3 client transport is disabled.

## Verification Checklist

- Python 3.11-3.14 package matrix passes.
- V2 SSE, poll, and FastAPI WebSocket golden fixtures are unchanged; a foreign
  supplied WebSocket conversation is denied before agent execution.
- V3 SSE and poll produce the same typed events, exactly one lineage event,
  globally unique event IDs, an exact successful event count, and one terminal
  event.
- Production starts only with authenticated routes; CORS/UI are explicit, and
  the optional UI has no remote or inline executable dependency.
- Read-only role and recursive tenant policy pass two-tenant Postgres tests.
- Built-in Python/package tools are inert, and production rejects registered
  arbitrary-execution capabilities; charts and artifacts have no executable path.
- ChartSpec and renderer reject active/unknown/oversized content.
- Schema version changes only when the canonical hash changes, and dotted
  identifier components cannot collide in snapshot or memory keys.
- Catalog sync is constrained to an explicit trusted schema/table allowlist.
- Semantic full coverage removes SQL; fallback and outage are visible.
- Lineage exists for success, zero-row, shortcut, limit, and failure paths.
- Corrected feedback affects the next retrieval in the same tenant only.
- Approved candidate export must improve evals without aggregate or slice
  regression.
