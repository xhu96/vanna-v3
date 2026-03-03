from __future__ import annotations

from typing import Optional

import pytest

from vanna.agents.basic import SimpleAgentMemory
from vanna.capabilities.schema_catalog import SchemaDiff, SchemaSnapshot, SchemaSyncResult
from vanna.core.user.models import User
from vanna.servers.base.models import ChatStreamChunk


class FakeUserResolver:
    async def resolve_user(self, request_context):
        return User(id="user-123", email="user@example.com")


class FakeAgent:
    def __init__(self):
        self.user_resolver = FakeUserResolver()
        self.agent_memory = SimpleAgentMemory()


class FakeChatHandler:
    def __init__(self):
        self.agent = FakeAgent()
        self.last_request = None

    async def handle_stream(self, chat_request):
        self.last_request = chat_request
        yield ChatStreamChunk(
            rich={"type": "text", "text": "ok"},
            simple=None,
            conversation_id=chat_request.conversation_id or "conv-generated",
            request_id=chat_request.request_id or "req-generated",
        )

    async def handle_poll(self, chat_request):
        self.last_request = chat_request
        return None


class FakeSchemaSyncService:
    def __init__(self):
        self.latest_snapshot: Optional[SchemaSnapshot] = SchemaSnapshot(
            snapshot_id="snap-before",
            dialect="sqlite",
            schema_hash="hash-before",
            columns=[],
        )
        self.run_scheduled_sync_calls = 0
        self.last_tool_context = None

    async def run_scheduled_sync_if_due(self, tool_context):
        self.run_scheduled_sync_calls += 1
        self.last_tool_context = tool_context
        self.latest_snapshot = SchemaSnapshot(
            snapshot_id="snap-after",
            dialect="sqlite",
            schema_hash="hash-after",
            columns=[],
        )
        return SchemaSyncResult(
            snapshot=self.latest_snapshot,
            diff=SchemaDiff(current_schema_hash=self.latest_snapshot.schema_hash),
        )

    async def get_latest_snapshot(self):
        return self.latest_snapshot


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_fastapi_chat_poll_runs_scheduled_schema_sync_before_handling_request():
    fastapi = pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")

    from vanna.servers.fastapi.routes import register_chat_routes

    app = fastapi.FastAPI()
    chat_handler = FakeChatHandler()
    schema_sync_service = FakeSchemaSyncService()

    register_chat_routes(
        app,
        chat_handler,
        {
            "schema_sync_service": schema_sync_service,
            "enable_default_ui_route": False,
        },
    )

    client = testclient.TestClient(app)
    response = client.post(
        "/api/vanna/v3/chat/poll",
        json={
            "message": "Show me total sales by country",
            "conversation_id": "conv-abc",
            "request_id": "req-abc",
            "metadata": {"client": "test"},
        },
    )

    assert response.status_code == 200
    assert schema_sync_service.run_scheduled_sync_calls == 1
    assert schema_sync_service.last_tool_context.conversation_id == "conv-abc"
    assert schema_sync_service.last_tool_context.request_id == "req-abc"
    assert chat_handler.last_request is not None
    assert chat_handler.last_request.metadata["client"] == "test"
    assert chat_handler.last_request.metadata["schema_hash"] == "hash-after"
    assert chat_handler.last_request.metadata["schema_snapshot_id"] == "snap-after"
    assert (
        chat_handler.last_request.request_context.metadata["schema_hash"]
        == "hash-after"
    )


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_flask_chat_poll_runs_scheduled_schema_sync_before_handling_request():
    flask = pytest.importorskip("flask")

    from vanna.servers.flask.routes import register_chat_routes

    app = flask.Flask(__name__)
    chat_handler = FakeChatHandler()
    schema_sync_service = FakeSchemaSyncService()

    register_chat_routes(
        app,
        chat_handler,
        {
            "schema_sync_service": schema_sync_service,
            "enable_default_ui_route": False,
        },
    )

    client = app.test_client()
    response = client.post(
        "/api/vanna/v3/chat/poll",
        json={
            "message": "Show me total sales by country",
            "conversation_id": "conv-flask",
            "request_id": "req-flask",
            "metadata": {"client": "test"},
        },
    )

    assert response.status_code == 200
    assert schema_sync_service.run_scheduled_sync_calls == 1
    assert schema_sync_service.last_tool_context.conversation_id == "conv-flask"
    assert schema_sync_service.last_tool_context.request_id == "req-flask"
    assert chat_handler.last_request is not None
    assert chat_handler.last_request.metadata["client"] == "test"
    assert chat_handler.last_request.metadata["schema_hash"] == "hash-after"
    assert chat_handler.last_request.metadata["schema_snapshot_id"] == "snap-after"
    assert (
        chat_handler.last_request.request_context.metadata["schema_snapshot_id"]
        == "snap-after"
    )
