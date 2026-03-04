# Migration Guide: Vanna v2 → v3

## Overview

Vanna v3 is an incremental evolution of v2. All v2 routes and the `LegacyVannaAdapter` remain fully available — you can migrate at your own pace.

**Key additions in v3:**

- Typed, versioned streaming events (`ChatEvent` with `event_version: "v3"`)
- Declarative chart payloads (`ChartSpec`) — no Python `exec()` for charts
- Read-only SQL policy enabled by default
- Schema drift sync with auto memory patching
- Feedback endpoint with immediate memory correction
- Direct SQL execution endpoint
- Full audit logging, lineage, evaluation framework
- Security middleware templates and rate limiting factories
- Skill fabric, personalization, and admin route modules

---

## Backward Compatibility

- **v2 routes stay available** — `/api/vanna/v2/chat_sse`, `/api/vanna/v2/chat_poll`, `/api/vanna/v2/chat_websocket` all continue to work unchanged.
- **`LegacyVannaAdapter`** remains supported for wrapping `VannaBase` instances (see [Migrating from LegacyVannaAdapter](#migrating-from-legacyvannaadapter) below).
- v2 clients can migrate incrementally by switching only endpoint URLs first.

---

## What Changes

### New v3 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/vanna/v3/chat/events` | Typed SSE streaming (replaces v2 `chat_sse`) |
| `POST` | `/api/vanna/v3/chat/poll` | Typed event polling (replaces v2 `chat_poll`) |
| `POST` | `/api/vanna/v3/schema/sync` | On-demand schema sync |
| `GET` | `/api/vanna/v3/schema/status` | Latest schema snapshot status |
| `POST` | `/api/vanna/v3/sql/run` | Direct SQL execution |
| `POST` | `/api/vanna/v3/feedback` | Feedback capture with memory patching |

Route prefixes are configurable via `api_v3_prefix` (default: `/api/vanna/v3`).

### Typed Event Envelope

v3 events use a typed envelope instead of raw JSON chunks:

```json
{
  "event_version": "v3",
  "event_type": "assistant_text",
  "conversation_id": "conv_123",
  "request_id": "req_123",
  "timestamp": 1739900000.12,
  "payload": {
    "rich": {},
    "simple": {}
  }
}
```

**Event types:**

| `event_type` | Meaning |
|--------------|---------|
| `status` | Progress / status updates |
| `assistant_text` | Text response chunks |
| `table_result` | Tabular data payload |
| `chart_spec` | Declarative chart (`vega-lite` or `plotly-json`) |
| `component` | Generic UI component |
| `error` | Error payload |
| `done` | Terminal event — stream complete |

**SSE framing:** Each event is sent as a named SSE event:
```
event: assistant_text
data: {"event_version":"v3","event_type":"assistant_text",...}

event: done
data: {"event_version":"v3","event_type":"done",...}
```

See the event envelope and types table above for the full reference.

### Declarative Charts (`ChartSpec`)

v3 replaces Python code execution for charts with a validated declarative model:

```python
from vanna.core.chart_spec import ChartSpec

# Two supported formats
spec = ChartSpec(
    format="vega-lite",        # or "plotly-json"
    schema_version="v5",
    spec={"mark": "bar", "encoding": {...}},
    dataset=[{"x": 1, "y": 2}, ...],
    metadata={"source": "query_123"},
)
```

**Security:** `ChartSpec` validates payloads — it blocks `url` keys and strings containing `javascript:`, `<script`, `Function(`, or `eval(`. No user-supplied code is ever executed.

The `VisualizeDataTool` auto-generates specs from data using `dataframe_to_vega_lite_spec()`, supporting chart types: `bar`, `horizontal_bar`, `line`, `scatter`, `pie`, `histogram`, `heatmap`.

### Agent Constructor: `agent_memory` Is Required

The `Agent` constructor now requires an `agent_memory` parameter:

```python
from vanna.agents.basic import SimpleAgentMemory

agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=my_resolver,
    agent_memory=SimpleAgentMemory(),  # required — no default
)
```

If you're using `LegacyVannaAdapter`, it implements both `ToolRegistry` and `AgentMemory`, so pass it for both:

```python
from vanna.legacy.adapter import LegacyVannaAdapter

adapter = LegacyVannaAdapter(vn)
agent = Agent(
    llm_service=llm,
    tool_registry=adapter,     # implements ToolRegistry
    user_resolver=my_resolver,
    agent_memory=adapter,      # implements AgentMemory
)
```

### New Agent Extensibility Points

v3 adds several optional constructor parameters for production customization:

| Parameter | Type | Purpose |
|-----------|------|---------|
| `lifecycle_hooks` | `List[LifecycleHook]` | Before/after message and tool execution hooks |
| `llm_middlewares` | `List[LlmMiddleware]` | Intercept/transform LLM requests and responses |
| `workflow_handler` | `WorkflowHandler` | Short-circuit LLM pipeline for custom flows |
| `error_recovery_strategy` | `ErrorRecoveryStrategy` | Custom retry/fallback on tool or LLM errors |
| `context_enrichers` | `List[ToolContextEnricher]` | Enrich tool execution context (RAG, memory) |
| `llm_context_enhancer` | `LlmContextEnhancer` | Inject context into LLM prompts (personalization, glossary) |
| `conversation_filters` | `List[ConversationFilter]` | Preprocess messages before LLM calls |
| `observability_provider` | `ObservabilityProvider` | Tracing and metrics |
| `audit_logger` | `AuditLogger` | Full audit event logging |
| `semantic_planner` | `SemanticFirstPlanner` | Semantic-first query routing |

### New Route Modules

v3 adds dedicated route modules beyond the core chat routes:

| Function | Prefix | Description |
|----------|--------|-------------|
| `register_admin_routes` | `/api/v1/admin` | Audit logs, tool RBAC, connections, observability, privacy |
| `register_lineage_routes` | `/api/v1/lineage` | Query lineage and markdown export |
| `register_security_routes` | `/api/v1/admin` | Runtime security configuration |
| `register_personalization_routes` | `/api/v1` | User/tenant profiles, glossary, consent |
| `register_skill_routes` | `/api/v1/skills` | Skill CRUD, compile, promote, rollback, generate |

All are in `app/fastapi/` (FastAPI) and `app/flask/` (Flask). When using `VannaFastAPIServer`, admin, lineage, and security routes are auto-registered. Personalization and skill routes require config:

```python
server = VannaFastAPIServer(agent=agent, config={
    "personalization": {"profile_store": ..., "glossary_store": ...},
    "skills": {"store": ..., "registry": ...},
})
```

---

## Client Migration Steps

1. **Keep existing v2 client logic** — verify everything still works unchanged.
2. **Switch to v3 SSE endpoint** — change `POST /api/vanna/v2/chat_sse` to `POST /api/vanna/v3/chat/events`.
3. **Parse typed event envelope** — each SSE event now has `event: <type>` and a `ChatEvent` JSON body with `event_type`, `payload.rich`, and `payload.simple`.
4. **Handle `chart_spec` events** — render `ChartSpec` payloads client-side using Vega-Lite or Plotly (no server-side code execution).
5. **Integrate feedback API** — `POST /api/vanna/v3/feedback` to submit corrected SQL for immediate memory patching.
6. **Enable schema sync** — call `POST /api/vanna/v3/schema/sync` on-demand or via a cron scheduler.

---

## Server Config Migration

### Using `VannaFastAPIServer`

```python
from app.fastapi.app import VannaFastAPIServer
from app.base import make_fastapi_bearer_auth_middleware, make_fixed_window_rate_limiter

server = VannaFastAPIServer(
    agent=agent,
    config={
        # Route prefixes
        "api_v2_prefix": "/api/vanna/v2",
        "api_v3_prefix": "/api/vanna/v3",
        "enable_default_ui_route": False,  # disable demo UI in production

        # Auth middleware
        "middleware_hooks": [
            make_fastapi_bearer_auth_middleware(my_token_validator),
        ],

        # Rate limiting (applied per-request via request_guard)
        "request_guard": make_fixed_window_rate_limiter(
            requests_per_minute=120,
        ),

        # CORS (only available via VannaFastAPIServer, not register_chat_routes)
        "cors": {
            "enabled": True,
            "allow_origins": ["https://my-ui.example.com"],
        },

        # v3 services
        "schema_sync_service": schema_sync,
        "feedback_service": feedback_service,
        "sql_runner": sql_runner,
    },
)
server.run(port=8000)
```

### Using `register_chat_routes` directly

```python
from app.fastapi.routes import register_chat_routes
from app.base import ChatHandler

app = FastAPI()
chat_handler = ChatHandler(agent)
register_chat_routes(app, chat_handler, config={
    "api_v2_prefix": "/api/vanna/v2",
    "api_v3_prefix": "/api/vanna/v3",
    "enable_default_ui_route": False,
    "request_guard": my_rate_limiter,
    "schema_sync_service": schema_sync,
    "feedback_service": feedback_service,
})
```

> **Note:** `cors` and `middleware_hooks` config keys are only read by `VannaFastAPIServer.create_app()`. If using `register_chat_routes` directly, configure CORS and middleware on your FastAPI app yourself.

---

## Migrating from LegacyVannaAdapter

The `LegacyVannaAdapter` wraps a `VannaBase` instance — it is **not** subclassed:

```python
from vanna.legacy.adapter import LegacyVannaAdapter

# Your existing VannaBase instance
vn = MyVanna(config={"model": "gpt-4o", ...})
vn.connect_to_postgres(...)
vn.train(...)

# Wrap it — adapter implements both ToolRegistry and AgentMemory
adapter = LegacyVannaAdapter(vn)

agent = Agent(
    llm_service=llm,
    tool_registry=adapter,
    user_resolver=my_resolver,
    agent_memory=adapter,
)
```

**What the adapter bridges:**

| v2 method | v3 interface | Notes |
|-----------|-------------|-------|
| `vn.run_sql()` | `RunSqlTool` | Registered for `["user", "admin"]` groups |
| `vn.get_similar_question_sql()` | `AgentMemory.search_similar_usage()` | Rank-based similarity scores |
| `vn.get_related_documentation()` | `AgentMemory.search_text_memories()` | Text memory search |
| `vn.add_question_sql()` | `AgentMemory.save_tool_usage()` | Only for `run_sql` tool |
| `vn.add_documentation()` | `AgentMemory.save_text_memory()` | Documentation storage |
| `vn.remove_training_data()` | `AgentMemory.delete_by_id()` | Training data removal |
| `vn.get_training_data()` | `SearchSavedCorrectToolUsesTool` | Searchable memory tool |

---

## Security Checklist

- [ ] Use DB credentials with **read-only grants**
- [ ] Attach auth middleware via `middleware_hooks` (use `make_fastapi_bearer_auth_middleware` or `make_flask_bearer_auth_middleware`)
- [ ] Add rate limiting via `request_guard` (use `make_fixed_window_rate_limiter`)
- [ ] Disable demo UI in production (`enable_default_ui_route: False`)
- [ ] Enable `AuditLogger` on the Agent for compliance logging
- [ ] Configure `access_groups` on all custom tools for permission enforcement
- [ ] Use `ChartSpec` declarative charts — never enable legacy Python chart execution

---

## See Also

- [Architecture & Design](architecture-and-design.md)
- [Production Example](../../examples/v3/fastapi_jwt_postgres.py)
- [SkillSpec Reference](skillspec-reference.md)
- [Personalization Guide](personalization.md)
- [Architecture & Threat Model](architecture-and-design.md#5-threat-model-and-mitigations)
