"""Regression tests for the documented BYO V3 SSE consumer."""

import importlib.util
import sys
from pathlib import Path

import pytest

EXAMPLE_PATH = Path(__file__).parents[1] / "examples/v3/byo_ui_event_stream.py"
SPEC = importlib.util.spec_from_file_location("vanna_v3_byo_example", EXAMPLE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
SseFrame = MODULE.SseFrame
V3SequenceState = MODULE.V3SequenceState
iter_sse_frames = MODULE.iter_sse_frames


def test_byo_parser_accumulates_multiline_data_and_ignores_comments() -> None:
    frames = list(
        iter_sse_frames(
            [
                ": heartbeat",
                "id: evt_1",
                "event: assistant_text",
                'data: {"event_version":"v3",',
                'data: "event_type":"assistant_text"}',
                "",
            ]
        )
    )

    assert frames == [
        SseFrame(
            event="assistant_text",
            event_id="evt_1",
            data='{"event_version":"v3",\n"event_type":"assistant_text"}',
        )
    ]


@pytest.mark.parametrize(
    "lines",
    [
        ["event: done", "data: {}", ""],
        ["id: evt_1", "data: {}", ""],
        ["id: evt_1", "event: done", "data: {}"],
    ],
)
def test_byo_parser_rejects_missing_metadata_or_incomplete_frames(
    lines: list[str],
) -> None:
    with pytest.raises(ValueError):
        list(iter_sse_frames(lines))


def envelope(event_type: str, sequence: int, payload: dict) -> tuple[object, dict]:
    value = {
        "event_version": "v3",
        "event_type": event_type,
        "event_id": f"evt_{sequence}",
        "sequence": sequence,
        "conversation_id": "conv_1",
        "request_id": "req_1",
        "payload": payload,
    }
    return SseFrame(event_type, value["event_id"], ""), value


def test_byo_sequence_requires_exactly_one_lineage_before_terminal() -> None:
    state = V3SequenceState()
    lineage_frame, lineage = envelope("lineage", 0, {"evidence": {}})
    done_frame, done = envelope("done", 1, {"status": "completed", "event_count": 2})

    assert state.accept(lineage_frame, lineage) == "lineage"
    assert state.accept(done_frame, done) == "done"
    state.finish()

    missing = V3SequenceState()
    premature_frame, premature = envelope(
        "done", 0, {"status": "completed", "event_count": 1}
    )
    with pytest.raises(ValueError, match="preceding lineage"):
        missing.accept(premature_frame, premature)

    duplicate = V3SequenceState()
    duplicate.accept(lineage_frame, lineage)
    duplicate_frame, duplicate_payload = envelope("lineage", 1, {"evidence": {}})
    with pytest.raises(ValueError, match="more than one lineage"):
        duplicate.accept(duplicate_frame, duplicate_payload)
