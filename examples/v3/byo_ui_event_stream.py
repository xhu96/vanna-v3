"""Golden path: custom client consuming v3 typed SSE events."""

import json
import requests


def stream_events(base_url: str, message: str, token: str) -> None:
    response = requests.post(
        f"{base_url}/api/vanna/v3/chat/events",
        headers={
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"message": message},
        stream=True,
        timeout=120,
    )
    response.raise_for_status()

    current_event = "message"
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        if raw_line.startswith("event: "):
            current_event = raw_line[7:].strip()
            continue
        if raw_line.startswith("data: "):
            payload = json.loads(raw_line[6:])
            print(f"[{current_event}] {payload['event_type']}")
            if payload["event_type"] == "done":
                break


if __name__ == "__main__":
    stream_events("http://localhost:8000", "Show revenue by month", "dev-token")

