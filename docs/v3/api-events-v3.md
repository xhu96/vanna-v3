# Vanna v3 Typed Streaming Events

## Endpoint
- SSE: `POST /api/vanna/v3/chat/events`
- Poll: `POST /api/vanna/v3/chat/poll`

Route prefixes are configurable with server config:
- `api_v2_prefix` (default `/api/vanna/v2`)
- `api_v3_prefix` (default `/api/vanna/v3`)

## Event Envelope
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

## Event Types
- `status`: status/progress updates
- `assistant_text`: assistant textual response chunks
- `table_result`: tabular data payload
- `chart_spec`: declarative chart payload (`vega-lite` or `plotly-json`)
- `component`: generic component payload
- `error`: error payload
- `done`: terminal event

## SSE Framing
Each message is emitted as:
```text
event: <event_type>
data: <json>
```

## Compatibility
- v2 endpoints remain unchanged.
- v3 events are additive and versioned for stable client contracts.
