"""Golden path: strict custom client consuming V3 typed SSE events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

import requests


@dataclass(frozen=True)
class SseFrame:
    event: str
    event_id: str
    data: str


@dataclass
class V3SequenceState:
    expected_sequence: int = 0
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None
    terminal: bool = False
    lineage: bool = False
    event_ids: set[str] = field(default_factory=set)

    def accept(self, frame: SseFrame, payload: object) -> str:
        if not isinstance(payload, dict) or payload.get("event_version") != "v3":
            raise ValueError("Unsupported V3 event envelope")
        if self.terminal:
            raise ValueError("V3 event followed the terminal event")
        if payload.get("event_type") != frame.event:
            raise ValueError("SSE event field does not match event_type")
        if payload.get("event_id") != frame.event_id:
            raise ValueError("SSE id field does not match event_id")
        if frame.event_id in self.event_ids:
            raise ValueError("V3 event_id was reused")
        if payload.get("sequence") != self.expected_sequence:
            raise ValueError("V3 sequence is not contiguous")

        current_conversation = payload.get("conversation_id")
        current_request = payload.get("request_id")
        if not isinstance(current_conversation, str) or not isinstance(
            current_request, str
        ):
            raise ValueError("V3 request identifiers are invalid")
        if self.expected_sequence == 0:
            self.conversation_id = current_conversation
            self.request_id = current_request
        elif (
            current_conversation != self.conversation_id
            or current_request != self.request_id
        ):
            raise ValueError("V3 request identifiers changed during the stream")

        event_type = payload["event_type"]
        if event_type == "lineage":
            if self.lineage:
                raise ValueError("V3 stream contains more than one lineage event")
            self.lineage = True
        elif event_type in {"done", "error"}:
            if not self.lineage:
                raise ValueError("V3 terminal event is missing preceding lineage")
            if event_type == "done":
                event_payload = payload.get("payload")
                if (
                    not isinstance(event_payload, dict)
                    or event_payload.get("event_count") != self.expected_sequence + 1
                ):
                    raise ValueError("V3 done event_count is invalid")
            self.terminal = True

        self.event_ids.add(frame.event_id)
        self.expected_sequence += 1
        return str(event_type)

    def finish(self) -> None:
        if not self.terminal:
            raise ValueError("V3 SSE response ended without done or error")
        if not self.lineage:
            raise ValueError("V3 SSE response ended without lineage")


def iter_sse_frames(lines: Iterable[str]) -> Iterator[SseFrame]:
    """Accumulate complete SSE frames, including multiline data fields."""

    event: Optional[str] = None
    event_id: Optional[str] = None
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                if not event or not event_id:
                    raise ValueError("V3 SSE frame is missing event or id")
                yield SseFrame(
                    event=event, event_id=event_id, data="\n".join(data_lines)
                )
            event = None
            event_id = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "id":
            event_id = value
        elif field == "data":
            data_lines.append(value)

    if data_lines:
        raise ValueError("V3 SSE response ended with an incomplete frame")


def stream_events(base_url: str, message: str, token: str) -> None:
    state = V3SequenceState()

    with requests.post(
        f"{base_url}/api/vanna/v3/chat/events",
        headers={
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"message": message},
        stream=True,
        timeout=(10, 120),
    ) as response:
        response.raise_for_status()
        lines = response.iter_lines(decode_unicode=True)
        for frame in iter_sse_frames(lines):
            payload = json.loads(frame.data)
            event_type = state.accept(frame, payload)
            assert isinstance(payload, dict)
            print(f"[{event_type}] {payload['payload']}")

    state.finish()


if __name__ == "__main__":
    stream_events("http://localhost:8000", "Show revenue by month", "dev-token")
