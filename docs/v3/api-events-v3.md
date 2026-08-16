# Vanna V3 Typed Event API

Status: normative contract. The FastAPI and Flask SSE/poll routes, shared
Pydantic event state machine, JSON Schemas, and web-component client transport
implement the framing and terminal invariants below. Agent-level evidence is
populated and finalized for success, shortcut, tool-limit, and failure paths.

- Event version: `v3`
- JSON Schema: `docs/v3/schemas/chat-events-v3.schema.json`
- Poll JSON Schema: `docs/v3/schemas/chat-poll-v3.schema.json`
- Chart schema: `docs/v3/schemas/chart-spec-v1.schema.json`
- Default prefix: `/api/vanna/v3`

## Routes

| Method | Default path | Response | Notes |
|---|---|---|---|
| `POST` | `/api/vanna/v3/chat/events` | `text/event-stream` | Typed V3 SSE over a fetch-compatible POST |
| `POST` | `/api/vanna/v3/chat/poll` | JSON event batch | Same event models and terminal rules as SSE |
| `POST` | `/api/vanna/v3/feedback` | JSON | Authenticated feedback owner |
| `GET` | `/api/vanna/v3/feedback/review` | JSON | Admin review queue; tenant-scoped |
| `POST` | `/api/vanna/v3/feedback/{feedback_id}/review` | JSON | Atomic admin approval/rejection |
| `GET` | `/api/vanna/v3/feedback/export` | JSON | Admin approved-only export plus manifest |
| `POST` | `/api/vanna/v3/schema/sync` | JSON | Admin by default |
| `GET` | `/api/vanna/v3/schema/status` | JSON | Admin by default |

Both FastAPI and Flask register the same V3 paths under configurable
`api_v3_prefix`. Route registration does not require the default UI route.
There is no V3 WebSocket route.

V2 paths and payloads are unchanged:

- `POST /api/vanna/v2/chat_sse`
- `POST /api/vanna/v2/chat_poll`
- FastAPI `WS /api/vanna/v2/chat_websocket`
- Flask `GET /api/vanna/v2/chat_websocket` returns documented `501`

## Authentication and Headers

Production mode requires an authenticated user and route authorization before
agent execution. A deployment can use its own cookie/JWT middleware or a
trusted OAuth gateway resolver.

Request headers:

- `Content-Type: application/json`
- `Accept: text/event-stream` for the SSE route
- application-specific authentication header/cookie
- optional `X-Request-ID`; the server validates and canonicalizes it

Response headers for SSE include:

- `Content-Type: text/event-stream; charset=utf-8`
- `Cache-Control: no-cache, no-transform`
- `X-Accel-Buffering: no` where supported
- bundled UI responses use `default-src 'none'`, same-origin scripts and
  connections, no object/worker/form capability, `frame-ancestors 'none'`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, and restrictive cross-origin/permissions headers

Authentication headers, cookies, DSNs, and tokens are never included in event
payloads or client logs.

### Optional Bundled UI

The root UI route is disabled unless `enable_default_ui_route=True` and still
requires the `ui:read` action in production. It is not part of the V3 client
contract. When enabled, it emits an inert V2-default `<vanna-chat>` shell with
exactly one module script and no inline JavaScript, demo cookie auth, popup, or
artifact execution helper. `component_script_path`, `api_base_url`, and API
prefixes are prevalidated same-origin absolute paths. The deprecated `cdn_url`
configuration name accepts a same-origin path only; external URLs fail server
registration. Operators self-host the built web-component bundle or omit this
route and consume the namespaced APIs directly.

## Chat Request

```json
{
  "message": "Show monthly revenue by region",
  "conversation_id": "conv_01J...",
  "request_id": "req_01J...",
  "metadata": {}
}
```

`message` is required and bounded by server configuration. IDs are optional;
the server creates them when absent. A supplied conversation ID is atomically
claimed before agent hooks, workflows, or model calls. An ID owned by a
different principal returns a pre-stream `403 conversation_access_denied` from
V2/V3 SSE and poll; it is never treated as a missing conversation. FastAPI V2
WebSocket messages re-resolve credentials, require the same tenant-qualified
principal as the handshake, apply the same atomic claim, and return the existing
redacted V2 error before schema or agent work.

Public `metadata` is contextual data only. It cannot supply tenant,
authorization, schema-lineage, or internal execution-mode state. The request
model accepts JSON values with finite numbers and enforces all of these limits:

- 64 KiB after compact UTF-8 JSON serialization;
- nesting depth at most 8;
- at most 100 entries in each object or list;
- strings at most 4,096 characters and keys at most 128 characters;
- no key beginning `_vanna_` and no `schema_hash`, `schema_snapshot_id`,
  `schema_version`, or `schema_drift_detected` key at any nesting level.

The server attaches trusted schema lineage after request validation. These
same metadata rules apply to V2 SSE/poll, V3 SSE/poll, and FastAPI V2
WebSocket requests.

## Event Envelope

Every event has these fields and rejects unknown envelope properties:

| Field | Type | Rule |
|---|---|---|
| `event_version` | string | Literal `v3` |
| `event_type` | enum | Discriminator listed below |
| `event_id` | string | Opaque ID, unique across the complete response; equals the SSE `id` value |
| `sequence` | integer | Starts at 0 and strictly increases by 1 per request |
| `conversation_id` | string | Server-canonical non-empty ID |
| `request_id` | string | Stable for all events in one request |
| `timestamp` | string | RFC 3339 UTC date-time |
| `payload` | object | Event-specific schema; unknown properties rejected |

Example:

```json
{
  "event_version": "v3",
  "event_type": "assistant_text",
  "event_id": "evt_01JABCDE",
  "sequence": 3,
  "conversation_id": "conv_01JABCDE",
  "request_id": "req_01JABCDE",
  "timestamp": "2026-08-08T14:00:43.123Z",
  "payload": {
    "text": "Revenue increased in Q2.",
    "delta": true
  }
}
```

## Payloads

### `status`

Progress only; it is not a terminal event.

```json
{"stage":"planning","message":"Checking semantic coverage"}
```

`stage` is one of `accepted`, `planning`, `semantic`, `sql`, `validating`, or
`rendering`.

### `assistant_text`

```json
{"text":"Revenue increased in Q2.","delta":true}
```

Text is untrusted model output. Clients render it as text or sanitized
markdown, never direct `innerHTML`.

### `table_result`

Inline payload:

```json
{
  "columns": ["month", "revenue"],
  "rows": [{"month":"2026-01","revenue":12500.0}],
  "row_count": 1,
  "truncated": false
}
```

Core V3 intentionally supports inline rows only. Larger source results are
truncated to the bounded inline payload and report the source `row_count`; no
unimplemented or arbitrary dataset-reference resolver is advertised.

### `chart_spec`

```json
{
  "chart_spec": {
    "format": "vega-lite",
    "schema_version": "v5-safe-1",
    "spec": {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "title": "Monthly revenue",
      "mark": "bar",
      "encoding": {
        "x": {"field":"month","type":"temporal"},
        "y": {"field":"revenue","type":"quantitative"}
      }
    },
    "dataset": [{"month":"2026-01","revenue":12500.0}],
    "metadata": {"row_count":1,"columns":["month","revenue"]}
  }
}
```

The server validates against the versioned safe ChartSpec profile before
emission. The client validates again before rendering. External URLs,
expressions, scripts, arbitrary transforms, unknown properties, non-finite
numbers, and oversized data are rejected.

### `component`

```json
{
  "component_kind": "code",
  "data": {"language":"sql","text":"SELECT 1"}
}
```

`component_kind` is an allowlist: `card`, `code`, or `artifact`. Unknown kinds
are not rendered. Artifact content has `representation` equal to `text` or
`sanitized_html`. Sanitized HTML is placed in an iframe with an empty sandbox
and restrictive CSP. JavaScript is represented as code text only.

### `warning`

```json
{
  "code": "semantic_coverage_missing",
  "message": "Semantic coverage is missing; the SQL fallback is enabled.",
  "fallback": "sql"
}
```

Warnings use stable codes. Full semantic coverage does not emit a fallback
warning because SQL is not offered. Service failure uses a terminal error by
default rather than a silent fallback.

### `lineage`

```json
{
  "evidence": {
    "schema_version": 7,
    "schema_snapshot_id": "snap_01JABCDE",
    "schema_hash": "sha256:...",
    "schema_drifted": false,
    "semantic": {"coverage":"full","metric_names":["revenue"]},
    "retrieved_sources": [{"id":"mem_123","kind":"memory","score":0.91}],
    "tool_calls": [{"name":"semantic_query","success":true,"runtime_ms":83.2}],
    "sql_executions": [],
    "validation_checks": [{"name":"row_shape","passed":true}],
    "confidence": {
      "tier": "High",
      "signals": ["semantic_full", "post_query_checks_passed"]
    }
  }
}
```

The lineage serializer filters SQL, memory text, tool arguments, and internal
errors according to the requesting user's permissions. Exactly one lineage
event is emitted before the terminal event for every accepted success or
failure. If an agent implementation omits it, the transport inserts a
Low-confidence lineage payload with `agent_lineage_emitted=false` instead of
allowing a lineage-free terminal event.

### `error`

```json
{
  "code": "query_policy_rejected",
  "message": "The query could not be executed safely.",
  "correlation_id": "err_01JABCDE",
  "retryable": false
}
```

`error` is terminal. `message` is public and non-sensitive. Raw exceptions,
SQL driver text, GraphQL bodies, stack traces, credentials, and DSNs are kept
out of the event. The correlation ID joins the response to redacted internal
logs.

### `done`

```json
{
  "status": "completed",
  "event_count": 8
}
```

`done` is terminal and only represents successful completion.

## Terminal State Machine

For every accepted chat request:

1. `sequence` starts at zero and increments by one.
2. Zero or more non-lineage non-terminal events may be emitted.
3. Exactly one `lineage` event is emitted as the final non-terminal event,
   immediately before termination.
4. Exactly one terminal `done` or `error` event is emitted.
5. No event is emitted after the terminal event.
6. An empty agent generator is converted into synthetic Low-confidence lineage
   followed by `done`; a conversion, generator, validation, or serialization
   failure becomes lineage followed by `error` when the connection remains
   writable. Client disconnect cancellation propagates and cannot guarantee a
   writable terminal frame.
7. Poll and SSE produce the same ordered logical events for the same execution.
8. The terminal event uses the same request and conversation IDs as every
   preceding event.
9. Every `event_id` is unique across non-terminal and terminal events.
10. A successful `done.payload.event_count` equals the total number of emitted
    events, including lineage and `done`; it therefore also equals the terminal
    sequence plus one.

An error before streaming headers are committed uses the HTTP error envelope
below. Once streaming begins, the status remains `200` and failure is expressed
as the terminal `error` event.

## SSE Wire Format

Each event is UTF-8 and framed with `id`, `event`, one or more `data` fields,
and a blank line:

```text
id: evt_01JABCDE
event: assistant_text
data: {"event_version":"v3","event_type":"assistant_text","event_id":"evt_01JABCDE","sequence":3,"conversation_id":"conv_01JABCDE","request_id":"req_01JABCDE","timestamp":"2026-08-08T14:00:43.123Z","payload":{"text":"Revenue increased.","delta":true}}

```

Clients must handle arbitrary byte fragmentation, multiple events per chunk,
multiline `data`, comments, UTF-8 boundaries, and LF, CRLF, or CR line endings.
They dispatch only at a blank line and validate `event` against the JSON
`event_type`.

The packaged web client exposes the typed stream without requiring the bundled
chat UI:

```typescript
import { VannaApiClient } from '@vanna/webcomponent';

const client = new VannaApiClient({
  protocol: 'v3',
  baseUrl: 'https://analytics.example.com',
  customHeaders: { Authorization: `Bearer ${token}` },
});

for await (const event of client.streamV3Events({
  message: 'Show monthly revenue',
})) {
  renderKnownEvent(event);
}
```

`streamV3Events` validates the closed envelope and payload models, ChartSpec,
SSE `id`/`event` metadata, contiguous sequence, stable request identifiers,
unique event IDs, exactly one final-non-terminal lineage event, and terminal placement before
yielding typed events. Its configured timeout remains active through SSE body
completion or poll JSON parsing, not merely until response headers arrive.
V3 clients default that deadline to 30 seconds. V2 keeps its historical lack of
an implicit body deadline unless the integrator explicitly configures one.

Because the endpoint is POST and execution can have side effects in memory and
audit state, the client never automatically replays the request by falling
back from SSE to poll after execution may have started. A retry requires an
explicit caller decision and the same idempotency/request ID policy.

## Poll Response

```json
{
  "event_version": "v3",
  "conversation_id": "conv_01JABCDE",
  "request_id": "req_01JABCDE",
  "events": [
    {
      "event_version": "v3",
      "event_type": "lineage",
      "event_id": "evt_01JABCDE_0",
      "sequence": 0,
      "conversation_id": "conv_01JABCDE",
      "request_id": "req_01JABCDE",
      "timestamp": "2026-08-08T14:00:43.122Z",
      "payload": {
        "evidence": {
          "schema_version": null,
          "schema_snapshot_id": null,
          "schema_hash": null,
          "schema_drifted": false,
          "semantic": {"coverage":"not_applicable","metric_names":[]},
          "retrieved_sources": [],
          "tool_calls": [],
          "sql_executions": [],
          "validation_checks": [{"name":"agent_lineage_emitted","passed":false}],
          "confidence": {"tier":"Low","signals":["missing_agent_lineage"]}
        }
      }
    }
  ],
  "terminal_event": {
    "event_version": "v3",
    "event_type": "done",
    "event_id": "evt_01JABCDE_1",
    "sequence": 1,
    "conversation_id": "conv_01JABCDE",
    "request_id": "req_01JABCDE",
    "timestamp": "2026-08-08T14:00:43.123Z",
    "payload": {"status":"completed","event_count":2}
  }
}
```

`events` contains non-terminal envelopes and ends with exactly one `lineage` envelope.
`terminal_event`
contains exactly one `done` or `error` envelope and is serialized after
`events`. This shape makes terminal-last explicit and structurally prevents an
event after terminal. Unknown fields are rejected. Runtime validation also
requires IDs to match the response envelope, sequence values to be contiguous
across `events` and `terminal_event`, every event ID to be globally unique,
`done.payload.event_count` to equal `len(events) + 1`, and lineage to occur
exactly once as the final non-terminal event. These cross-item invariants are enforced by the
Python and TypeScript runtime validators because JSON Schema cannot express all
of them.

## HTTP Error Envelope

Errors detected before an execution is accepted use:

```json
{
  "error": {
    "code": "authentication_required",
    "message": "Authentication is required.",
    "correlation_id": "err_01JABCDE",
    "retryable": false
  }
}
```

Required mappings:

| Status | Example stable code |
|---|---|
| `400` | `invalid_request` |
| `401` | `authentication_required` |
| `403` | `route_access_denied`, `conversation_access_denied` |
| `404` | `conversation_not_found` |
| `409` | `request_conflict` |
| `413` | `payload_too_large` |
| `429` | `rate_limit_exceeded` |
| `500` | `internal_error` |
| `503` | `semantic_service_unavailable` |

Framework exception details never alter the public schema.

## Versioning

- Additive payload changes require an explicit schema change that does not
  invalidate existing clients.
- Removing/renaming fields, changing terminal semantics, or changing payload
  meaning requires a new event version and route contract.
- Unknown `event_version`, `event_type`, component kind, ChartSpec profile, or
  required field fails closed in the V3 client.
- V2 remains the frontend default and is not implemented as a lossy automatic
  conversion from V3.
