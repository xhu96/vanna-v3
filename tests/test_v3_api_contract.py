"""FastAPI/Flask V3 SSE and poll parity regressions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional

import pytest
from fastapi.testclient import TestClient

from vanna.capabilities.schema_catalog import get_latest_snapshot_compat
from vanna.components import RichTextComponent
from vanna.core.tool import ToolContext
from vanna.core.storage import Conversation
from vanna.core.user import RequestContext, User, UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.servers.base.events_v3 import ChatEvent, ChatPollResponse
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.servers.flask import VannaFlaskServer

FRAMEWORKS = ("fastapi", "flask")
AUTH_HEADERS = {"Authorization": "Bearer test"}


class Resolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        if request_context.get_header("Authorization") == "Bearer test":
            return User(
                id="api-user",
                authenticated=True,
                metadata={"tenant_id": "tenant-a"},
                group_memberships=["user"],
            )
        return User(id="anonymous", authenticated=False)


class ConversationStore:
    supports_atomic_ownership = True
    supports_atomic_updates = True

    async def claim_conversation(self, *args: Any, **_kwargs: Any) -> Any:
        conversation_id, user = args
        return Conversation(id=conversation_id, user=user, messages=[]), True


class LegacySchemaService:
    """V2 extension point retained while context-aware V3 services migrate."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_latest_snapshot(self) -> None:
        self.calls += 1
        return None


@dataclass
class MalformedChartComponent:
    def serialize_for_frontend(self) -> dict[str, Any]:
        return {
            "type": "chart",
            "data": {
                "format": "vega-lite",
                "schema_version": "v5-safe-1",
                "spec": {"mark": "bar", "url": "https://attacker.invalid/data"},
                "dataset": [],
                "metadata": {"row_count": 0, "columns": []},
            },
        }


class ApiAgent:
    def __init__(
        self,
        *,
        mode: str = "text",
        secret: str = "TOP_SECRET",
    ) -> None:
        self.user_resolver = Resolver()
        self.conversation_store = ConversationStore()
        self.agent_memory = DemoAgentMemory()
        self.mode = mode
        self.secret = secret
        self.calls = 0

    async def send_message(
        self,
        *,
        request_context: RequestContext,
        message: str,
        conversation_id: str,
    ) -> AsyncGenerator[Any, None]:
        del request_context, message, conversation_id
        self.calls += 1
        if self.mode == "empty":
            return
        if self.mode == "malformed_chart":
            yield MalformedChartComponent()
            return
        yield RichTextComponent(content="Revenue increased.", markdown=False)
        if self.mode == "failure":
            raise RuntimeError(f"database password {self.secret}")


def make_client(
    framework: str,
    agent: ApiAgent,
    config: Optional[dict[str, Any]] = None,
) -> Any:
    if framework == "fastapi":
        app = VannaFastAPIServer(agent, config).create_app()  # type: ignore[arg-type]
        return TestClient(app, raise_server_exceptions=False)
    app = VannaFlaskServer(agent, config).create_app()  # type: ignore[arg-type]
    return app.test_client()


def response_text(response: Any) -> str:
    if hasattr(response, "get_data"):
        return str(response.get_data(as_text=True))
    return str(response.text)


def response_json(response: Any) -> dict[str, Any]:
    value = response.json() if callable(response.json) else response.json
    assert isinstance(value, dict)
    return value


def parse_sse(text: str) -> list[ChatEvent]:
    events: list[ChatEvent] = []
    for frame in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        if not frame:
            continue
        event_name: Optional[str] = None
        event_id: Optional[str] = None
        data_lines: list[str] = []
        for line in frame.split("\n"):
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        assert event_name is not None
        assert event_id is not None
        event = ChatEvent.model_validate_json("\n".join(data_lines))
        assert event.event_type == event_name
        assert event.event_id == event_id
        events.append(event)
    return events


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("endpoint", ("chat_poll", "chat_sse"))
def test_v2_routes_preserve_no_argument_schema_service_hook(
    framework: str,
    endpoint: str,
) -> None:
    service = LegacySchemaService()
    client = make_client(
        framework,
        ApiAgent(),
        {"schema_sync_service": service},
    )

    with pytest.warns(DeprecationWarning, match="get_latest_snapshot"):
        response = client.post(
            f"/api/vanna/v2/{endpoint}",
            json={"message": "hello"},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert service.calls == 1


@pytest.mark.asyncio
async def test_schema_snapshot_compat_rejects_malformed_metadata() -> None:
    class MalformedSchemaService:
        async def get_latest_snapshot(self, context: Any) -> object:
            del context
            return object()

    context = ToolContext(
        user=User(id="api-user", metadata={"tenant_id": "tenant-a"}),
        conversation_id="conversation-1",
        request_id="request-1",
        agent_memory=DemoAgentMemory(),
    )

    with pytest.raises(TypeError, match="schema snapshot metadata"):
        await get_latest_snapshot_compat(MalformedSchemaService(), context)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_empty_sse_and_poll_return_one_done_with_canonical_ids(framework: str) -> None:
    agent = ApiAgent(mode="empty")
    client = make_client(framework, agent)
    request = {"message": "hello"}

    stream = client.post(
        "/api/vanna/v3/chat/events",
        json=request,
        headers={**AUTH_HEADERS, "Accept": "text/event-stream"},
    )
    poll = client.post(
        "/api/vanna/v3/chat/poll",
        json=request,
        headers=AUTH_HEADERS,
    )

    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "no-transform" in stream.headers["cache-control"]
    stream_events = parse_sse(response_text(stream))
    assert [event.event_type for event in stream_events] == ["lineage", "done"]
    assert [event.sequence for event in stream_events] == [0, 1]
    assert stream_events[0].conversation_id.startswith("conv_")
    assert stream_events[0].request_id.startswith("req_")

    poll_response = ChatPollResponse.model_validate_json(response_text(poll))
    assert [event.event_type for event in poll_response.events] == ["lineage"]
    assert poll_response.terminal_event.event_type == "done"
    assert poll_response.terminal_event.sequence == 1
    assert poll_response.conversation_id.startswith("conv_")
    assert poll_response.request_id.startswith("req_")
    assert agent.calls == 2


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_sse_and_poll_have_same_logical_success_events(framework: str) -> None:
    agent = ApiAgent()
    client = make_client(framework, agent)
    request = {
        "message": "hello",
        "conversation_id": "conv_fixed",
        "request_id": "req_fixed",
    }

    stream = client.post(
        "/api/vanna/v3/chat/events",
        json=request,
        headers=AUTH_HEADERS,
    )
    poll = client.post(
        "/api/vanna/v3/chat/poll",
        json=request,
        headers=AUTH_HEADERS,
    )
    stream_events = parse_sse(response_text(stream))
    poll_response = ChatPollResponse.model_validate_json(response_text(poll))
    poll_events = [*poll_response.events, poll_response.terminal_event]

    assert [event.event_type for event in stream_events] == [
        "assistant_text",
        "lineage",
        "done",
    ]
    assert [event.event_type for event in poll_events] == [
        "assistant_text",
        "lineage",
        "done",
    ]
    assert [event.sequence for event in stream_events] == [0, 1, 2]
    assert [event.sequence for event in poll_events] == [0, 1, 2]
    assert all(event.conversation_id == "conv_fixed" for event in stream_events)
    assert all(event.request_id == "req_fixed" for event in stream_events)


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("mode", ["failure", "malformed_chart"])
def test_execution_and_conversion_failures_are_terminal_and_redacted(
    framework: str,
    mode: str,
) -> None:
    secret = "postgresql://user:password@secret-host/database"
    agent = ApiAgent(mode=mode, secret=secret)
    client = make_client(framework, agent)
    request = {
        "message": "hello",
        "conversation_id": "conv_fixed",
        "request_id": "req_fixed",
    }

    stream = client.post(
        "/api/vanna/v3/chat/events",
        json=request,
        headers=AUTH_HEADERS,
    )
    poll = client.post(
        "/api/vanna/v3/chat/poll",
        json=request,
        headers=AUTH_HEADERS,
    )
    stream_events = parse_sse(response_text(stream))
    poll_response = ChatPollResponse.model_validate_json(response_text(poll))
    poll_events = [*poll_response.events, poll_response.terminal_event]

    assert stream_events[-1].event_type == "error"
    assert poll_events[-1].event_type == "error"
    assert sum(event.terminal for event in stream_events) == 1
    assert sum(event.terminal for event in poll_events) == 1
    assert sum(event.event_type == "lineage" for event in stream_events) == 1
    assert sum(event.event_type == "lineage" for event in poll_events) == 1
    assert all(event.event_type != "done" for event in stream_events)
    serialized = response_text(stream) + response_text(poll)
    assert secret not in serialized
    assert "internal_error" in serialized


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_v3_invalid_ids_are_400_before_agent_execution(framework: str) -> None:
    agent = ApiAgent()
    client = make_client(framework, agent)

    response = client.post(
        "/api/vanna/v3/chat/poll",
        json={
            "message": "hello",
            "conversation_id": "bad\nidentifier",
            "request_id": "req_fixed",
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    payload = response_json(response)
    assert payload["error"]["code"] == "invalid_request"
    assert agent.calls == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_v3_custom_prefix_is_independent_of_ui_routes(framework: str) -> None:
    agent = ApiAgent(mode="empty")
    client = make_client(
        framework,
        agent,
        {
            "api_v3_prefix": "/tenant/events/v3",
            "enable_default_ui_route": False,
        },
    )

    assert (
        client.post(
            "/api/vanna/v3/chat/poll",
            json={"message": "hello"},
            headers=AUTH_HEADERS,
        ).status_code
        == 404
    )
    response = client.post(
        "/tenant/events/v3/chat/poll",
        json={"message": "hello"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert (
        ChatPollResponse.model_validate_json(
            response_text(response)
        ).terminal_event.event_type
        == "done"
    )
    assert client.get("/").status_code == 404
