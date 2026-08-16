"""Strict framework-neutral V3 event contract regressions."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncGenerator

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError
from referencing import Registry, Resource

from vanna.servers.base.errors import InternalServerError
from vanna.servers.base.events_v3 import (
    AssistantTextPayload,
    ChatEvent,
    ChatPollResponse,
    DonePayload,
    ErrorPayload,
    LineageEvidencePayload,
    LineagePayload,
    V3EventSequence,
    collect_v3_poll,
    format_sse_event,
    iter_v3_events,
    prepare_v3_request,
)
from vanna.servers.base.models import ChatRequest, ChatStreamChunk

ROOT = Path(__file__).parents[1]


def chunk(rich: dict, *, conversation_id: str = "conv_1") -> ChatStreamChunk:
    return ChatStreamChunk(
        rich=rich,
        simple=None,
        conversation_id=conversation_id,
        request_id="req_1",
        timestamp=1_786_000_000.125,
    )


def chart_spec() -> dict:
    return {
        "format": "vega-lite",
        "schema_version": "v5-safe-1",
        "spec": {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "bar",
            "encoding": {
                "x": {"field": "month", "type": "nominal"},
                "y": {"field": "revenue", "type": "quantitative"},
            },
        },
        "dataset": [{"month": "2026-01", "revenue": 12.5}],
        "metadata": {"row_count": 1, "columns": ["month", "revenue"]},
    }


def lineage_payload() -> LineagePayload:
    return LineagePayload(
        evidence=LineageEvidencePayload(
            schema_version=None,
            schema_snapshot_id=None,
            schema_hash=None,
            schema_drifted=False,
            semantic={"coverage": "not_applicable", "metric_names": []},
            confidence={"tier": "Low", "signals": []},
        )
    )


def event_validator() -> Draft202012Validator:
    event_schema = json.loads(
        (ROOT / "docs/v3/schemas/chat-events-v3.schema.json").read_text()
    )
    chart_schema = json.loads(
        (ROOT / "docs/v3/schemas/chart-spec-v1.schema.json").read_text()
    )
    registry = Registry().with_resources(
        [
            (event_schema["$id"], Resource.from_contents(event_schema)),
            (chart_schema["$id"], Resource.from_contents(chart_schema)),
        ]
    )
    return Draft202012Validator(event_schema, registry=registry)


@pytest.mark.parametrize(
    ("rich", "event_type"),
    [
        (
            {
                "type": "status_bar_update",
                "data": {"status": "working", "message": "Planning"},
            },
            "status",
        ),
        (
            {"type": "text", "data": {"content": "Revenue increased."}},
            "assistant_text",
        ),
        (
            {
                "type": "dataframe",
                "data": {
                    "columns": ["month", "revenue"],
                    "data": [{"month": "2026-01", "revenue": 12.5}],
                    "row_count": 1,
                },
            },
            "table_result",
        ),
        ({"type": "chart", "data": chart_spec()}, "chart_spec"),
        (
            {"type": "card", "data": {"title": "Evidence", "content": "Body"}},
            "component",
        ),
        (
            {
                "type": "artifact",
                "data": {
                    "title": "Unsafe legacy artifact",
                    "artifact_type": "javascript",
                    "content": "window.top.location='https://attacker.invalid'",
                },
            },
            "component",
        ),
        (
            {
                "type": "status_bar_update",
                "data": {
                    "status": "warning",
                    "message": "SQL fallback route",
                    "detail": "Semantic coverage is missing; SQL is enabled.",
                    "code": "semantic_coverage_missing",
                    "fallback": "sql",
                },
            },
            "warning",
        ),
    ],
)
def test_chunk_conversion_produces_schema_valid_typed_payloads(
    rich: dict,
    event_type: str,
) -> None:
    event = ChatEvent.from_chunk(chunk(rich))

    assert event.event_version == "v3"
    assert event.event_type == event_type
    assert event.sequence == 0
    assert event.timestamp.tzinfo is not None
    event_validator().validate(event.model_dump(mode="json"))


def test_chart_event_contains_only_revalidated_chart_spec() -> None:
    event = ChatEvent.from_chunk(
        chunk(
            {
                "type": "chart",
                "data": {
                    **chart_spec(),
                    "chart_type": "declarative",
                    "config": {"unsafe": "ignored by V3 envelope"},
                },
            }
        )
    )

    payload = event.payload
    assert payload.chart_spec.model_dump() == chart_spec()  # type: ignore[union-attr]


def test_artifact_event_is_inert_source_text_not_executable_html() -> None:
    event = ChatEvent.from_chunk(
        chunk(
            {
                "type": "artifact",
                "data": {
                    "artifact_type": "html",
                    "content": "<script>window.top.pwned=true</script>",
                },
            }
        )
    )
    payload = event.model_dump(mode="json")["payload"]

    assert payload["component_kind"] == "artifact"
    assert payload["data"]["representation"] == "text"
    assert "<script>" in payload["data"]["content"]


def test_event_payload_discriminator_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ChatEvent(
            event_type="done",
            conversation_id="conv_1",
            request_id="req_1",
            payload={"status": "completed", "event_count": 1, "extra": True},
        )
    with pytest.raises(ValidationError):
        ChatEvent(
            event_type="done",
            conversation_id="conv_1",
            request_id="req_1",
            payload={"text": "wrong discriminator", "delta": False},
        )


def test_event_serialization_revalidates_mutated_nested_payload() -> None:
    event = ChatEvent(
        event_type="assistant_text",
        conversation_id="conv_1",
        request_id="req_1",
        payload=AssistantTextPayload(text="safe", delta=False),
    )
    event.payload.__dict__["text"] = "x" * 1_000_001

    with pytest.raises((ValidationError, PydanticSerializationError)):
        event.model_dump_json()


def test_done_and_error_payloads_are_typed_and_redacted() -> None:
    done = ChatEvent.done("conv_1", "req_1", sequence=3)
    error = ChatEvent.error(
        "conv_1",
        "req_1",
        InternalServerError(correlation_id="err_safe"),
        sequence=3,
    )

    assert isinstance(done.payload, DonePayload)
    assert done.payload.status == "completed"
    assert done.payload.event_count == 4
    assert isinstance(error.payload, ErrorPayload)
    assert error.payload.model_dump() == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "correlation_id": "err_safe",
        "retryable": False,
    }


def test_serialized_event_round_trips_with_strict_utc_timestamp() -> None:
    event = ChatEvent.done("conv_1", "req_1")

    parsed = ChatEvent.model_validate_json(event.model_dump_json())

    assert parsed == event
    with pytest.raises(ValidationError, match="UTC offset"):
        ChatEvent(
            event_type="done",
            conversation_id="conv_1",
            request_id="req_1",
            timestamp="2026-08-11T12:00:00",
            payload={"status": "completed", "event_count": 1},
        )


def test_lineage_payload_matches_documented_discriminator() -> None:
    payload = lineage_payload()
    event = ChatEvent(
        event_type="lineage",
        conversation_id="conv_1",
        request_id="req_1",
        payload=payload,
    )
    event_validator().validate(event.model_dump(mode="json"))


def test_sequence_rejects_identifier_changes_and_post_terminal_events() -> None:
    sequence = V3EventSequence(
        "conv_1",
        "req_1",
        event_id_factory=iter(["evt_1", "evt_2", "evt_rejected", "evt_3"]).__next__,
    )
    first = sequence.from_chunk(chunk({"type": "text", "data": {"content": "hello"}}))
    lineage = sequence.lineage(lineage_payload())
    with pytest.raises(ValueError, match="final non-terminal"):
        sequence.from_chunk(chunk({"type": "text", "data": {"content": "too late"}}))
    terminal = sequence.done()

    assert first.event_id == "evt_1"
    assert first.sequence == 0
    assert lineage.event_id == "evt_2"
    assert lineage.sequence == 1
    assert terminal.event_id == "evt_3"
    assert terminal.sequence == 2
    with pytest.raises(RuntimeError, match="already terminated"):
        sequence.done()

    mismatched = V3EventSequence("conv_1", "req_1")
    with pytest.raises(ValueError, match="identifiers changed"):
        mismatched.from_chunk(
            chunk(
                {"type": "text", "data": {"content": "hello"}},
                conversation_id="conv_other",
            )
        )

    without_lineage = V3EventSequence("conv_1", "req_1")
    with pytest.raises(RuntimeError, match="preceding lineage"):
        without_lineage.done()


async def empty_chunks() -> AsyncGenerator[ChatStreamChunk, None]:
    if False:
        yield chunk({"type": "text", "data": {"content": "never"}})


async def failing_chunks() -> AsyncGenerator[ChatStreamChunk, None]:
    yield chunk({"type": "text", "data": {"content": "before failure"}})
    raise RuntimeError("database password TOP_SECRET")


async def blocked_chunks(
    started: asyncio.Event,
    closed: asyncio.Event,
) -> AsyncGenerator[ChatStreamChunk, None]:
    try:
        started.set()
        await asyncio.Event().wait()
        yield chunk({"type": "text", "data": {"content": "never"}})
    finally:
        closed.set()


@pytest.mark.asyncio
async def test_empty_stream_and_failure_each_have_exactly_one_terminal() -> None:
    empty = [
        event
        async for event in iter_v3_events(
            empty_chunks(), conversation_id="conv_1", request_id="req_1"
        )
    ]
    failed = [
        event
        async for event in iter_v3_events(
            failing_chunks(),
            conversation_id="conv_1",
            request_id="req_1",
            internal_error_factory=lambda: InternalServerError(
                correlation_id="err_public"
            ),
        )
    ]

    assert [event.event_type for event in empty] == ["lineage", "done"]
    assert [event.sequence for event in empty] == [0, 1]
    assert [event.event_type for event in failed] == [
        "assistant_text",
        "lineage",
        "error",
    ]
    assert [event.sequence for event in failed] == [0, 1, 2]
    assert failed[1].payload.evidence.confidence.signals == [
        "missing_agent_lineage",
        "request_failed",
    ]
    serialized = json.dumps([event.model_dump(mode="json") for event in failed])
    assert "TOP_SECRET" not in serialized
    assert "err_public" in serialized


@pytest.mark.asyncio
async def test_cancellation_propagates_without_a_synthetic_terminal_event() -> None:
    started = asyncio.Event()
    closed = asyncio.Event()
    stream = iter_v3_events(
        blocked_chunks(started, closed),
        conversation_id="conv_1",
        request_id="req_1",
    )
    pending = asyncio.create_task(anext(stream))
    await started.wait()

    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(closed.wait(), timeout=1)


@pytest.mark.asyncio
async def test_poll_response_structurally_separates_terminal_event() -> None:
    response = await collect_v3_poll(
        empty_chunks(),
        conversation_id="conv_1",
        request_id="req_1",
    )

    assert [event.event_type for event in response.events] == ["lineage"]
    assert response.terminal_event.event_type == "done"
    assert response.terminal_event.sequence == 1

    with pytest.raises(ValidationError, match="terminal_event"):
        ChatPollResponse(
            conversation_id="conv_1",
            request_id="req_1",
            events=[],
            terminal_event=ChatEvent(
                event_type="assistant_text",
                conversation_id="conv_1",
                request_id="req_1",
                payload=AssistantTextPayload(text="not terminal", delta=False),
            ),
        )

    with pytest.raises(ValidationError, match="exactly one lineage"):
        ChatPollResponse(
            conversation_id="conv_1",
            request_id="req_1",
            events=[],
            terminal_event=ChatEvent.done("conv_1", "req_1"),
        )

    with pytest.raises(ValidationError, match="final non-terminal"):
        ChatPollResponse(
            conversation_id="conv_1",
            request_id="req_1",
            events=[
                ChatEvent.lineage("conv_1", "req_1", lineage_payload(), sequence=0),
                ChatEvent(
                    event_type="assistant_text",
                    sequence=1,
                    conversation_id="conv_1",
                    request_id="req_1",
                    payload=AssistantTextPayload(text="too late", delta=False),
                ),
            ],
            terminal_event=ChatEvent.done("conv_1", "req_1", sequence=2),
        )


def test_sse_frame_has_matching_id_event_and_single_json_data_record() -> None:
    event = ChatEvent.done(
        "conv_1",
        "req_1",
        event_id="evt_fixed",
    )
    frame = format_sse_event(event)

    assert frame.startswith("id: evt_fixed\nevent: done\ndata: {")
    assert frame.endswith("\n\n")
    data_line = frame.splitlines()[2]
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["event_id"] == "evt_fixed"
    assert payload["event_type"] == "done"


def test_event_conversion_and_serialization_p95_is_below_budget() -> None:
    source = chunk({"type": "text", "data": {"content": "Revenue increased."}})
    for _ in range(20):
        ChatEvent.from_chunk(source).model_dump_json()

    samples_ms = []
    for _ in range(200):
        started = time.perf_counter()
        ChatEvent.from_chunk(source).model_dump_json()
        samples_ms.append((time.perf_counter() - started) * 1000)

    p95_ms = sorted(samples_ms)[189]
    assert p95_ms < 5, f"V3 event conversion/serialization p95 was {p95_ms:.2f} ms"


def test_prepare_v3_request_assigns_ids_and_rejects_invalid_supplied_ids() -> None:
    request = ChatRequest(message="hello")
    prepare_v3_request(request)
    assert request.conversation_id.startswith("conv_")
    assert request.request_id.startswith("req_")

    for invalid in ("", " leading", "x" * 161, "bad\nvalue"):
        with pytest.raises(ValueError):
            prepare_v3_request(
                ChatRequest(
                    message="hello",
                    conversation_id=invalid,
                    request_id="req_1",
                )
            )


def test_poll_rejects_duplicate_event_ids_and_mismatched_done_count() -> None:
    lineage = ChatEvent.lineage(
        "conv_1",
        "req_1",
        lineage_payload(),
        sequence=0,
        event_id="evt_same",
    )
    duplicate_done = ChatEvent.done(
        "conv_1",
        "req_1",
        sequence=1,
        event_id="evt_same",
    )

    with pytest.raises(ValidationError, match="IDs must be unique"):
        ChatPollResponse(
            conversation_id="conv_1",
            request_id="req_1",
            events=[lineage],
            terminal_event=duplicate_done,
        )

    wrong_count_done = ChatEvent(
        event_type="done",
        event_id="evt_done",
        sequence=1,
        conversation_id="conv_1",
        request_id="req_1",
        payload=DonePayload(event_count=99),
    )
    with pytest.raises(ValidationError, match="event_count"):
        ChatPollResponse(
            conversation_id="conv_1",
            request_id="req_1",
            events=[lineage.model_copy(update={"event_id": "evt_lineage"})],
            terminal_event=wrong_count_done,
        )
