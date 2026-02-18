"""Tests for v3 typed streaming events."""

from vanna.servers.base.events_v3 import ChatEvent
from vanna.servers.base.models import ChatStreamChunk


def test_chat_event_maps_chart_chunk_to_chart_spec():
    chunk = ChatStreamChunk(
        rich={"type": "chart", "data": {"format": "vega-lite"}},
        simple=None,
        conversation_id="conv_1",
        request_id="req_1",
    )
    event = ChatEvent.from_chunk(chunk)
    assert event.event_version == "v3"
    assert event.event_type == "chart_spec"
    assert event.payload["rich"]["type"] == "chart"


def test_chat_event_done_has_typed_done_event():
    event = ChatEvent.done("conv_2", "req_2")
    assert event.event_version == "v3"
    assert event.event_type == "done"
    assert event.payload["status"] == "done"
