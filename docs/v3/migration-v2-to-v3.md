# Migration Guide: Vanna v2 -> v3

## What Changes in v3
- Typed versioned stream events at `/api/vanna/v3/*`.
- Declarative chart payloads (`ChartSpec`) replace implicit Python chart execution.
- Read-only SQL policy is enabled by default in `RunSqlTool`.
- Schema drift sync endpoints:
  - `POST /api/vanna/v3/schema/sync`
  - `GET /api/vanna/v3/schema/status`
- Feedback endpoint with immediate memory patching:
  - `POST /api/vanna/v3/feedback`

## Backward Compatibility
- v2 routes stay available (`/api/vanna/v2/*` by default).
- `LegacyVannaAdapter` remains supported.
- v2 clients can migrate incrementally by switching only endpoint URLs first.

## Breaking-Safety Change
Legacy Python chart execution is now disabled by default:
```python
vn = MyLegacyVanna(config={
    "allow_unsafe_plotly_code_execution": False,  # default in v3
})
```

To opt in (admin-only environments), set:
```python
vn = MyLegacyVanna(config={
    "allow_unsafe_plotly_code_execution": True
})
```

## Client Migration Steps
1. Keep existing v2 client logic, verify parity.
2. Switch to v3 stream endpoint and parse typed event envelope.
3. Handle `chart_spec` payloads for declarative rendering.
4. Integrate feedback API and pass corrected SQL for memory patching.
5. Enable schema sync scheduler or call on-demand sync endpoint.

## Server Config Migration
```python
config = {
    "api_v2_prefix": "/api/vanna/v2",
    "api_v3_prefix": "/api/vanna/v3",
    "enable_default_ui_route": False,  # BYO UI
    "cors": {
        "enabled": True,
        "allow_origins": ["https://my-ui.example.com"]
    }
}
```

## Security Migration Checklist
- Use DB credentials with read-only grants.
- Attach auth middleware via `middleware_hooks`.
- Add request throttling via `request_guard` (rate limit hook).
- Disable default demo UI route in production (`enable_default_ui_route=False`).
