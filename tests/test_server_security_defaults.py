"""Hermetic production-mode security contracts for both HTTP servers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from flask import Flask
from pydantic import BaseModel

from vanna.agents.basic import SimpleAgentMemory, SimpleUserResolver
from vanna.core.audit import AuditEvent, AuditEventType
from vanna.core import User
from vanna.core.registry import ToolRegistry
from vanna.core.tool import (
    ARBITRARY_CODE_EXECUTION_CAPABILITY,
    PRIVILEGED_SQL_WRITE_CAPABILITY,
    ToolCall,
    ToolContext,
    ToolResult,
)
from vanna.core.llm import LlmRequest
from vanna.core.storage import (
    Conversation,
    ConversationAccessDeniedError,
    Message,
    REQUEST_ID_METADATA_KEY,
)
from vanna.core.user import RequestContext, UserResolver
from vanna.services.feedback import FeedbackService
from vanna.services.feedback_store import FeedbackStateError
from vanna.integrations.local.audit import LoggingAuditLogger
from vanna.integrations.anthropic.llm import AnthropicLlmService
from vanna.integrations.google.gemini import GeminiLlmService
from vanna.integrations.openai.responses import OpenAIResponsesService
from vanna.servers.base import (
    CHAT_EXECUTE,
    FixedWindowRateLimiter,
    RouteAuthorizer,
)
from vanna.servers.base.authorization import RESOLVED_USER_METADATA_KEY
from vanna.servers.base.errors import RateLimitExceededError
from vanna.servers.base.rate_limit import configured_rate_limiter
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.servers.flask import VannaFlaskServer
from vanna.tools.python import (
    PipInstallArgs,
    PipInstallTool,
    RunPythonFileArgs,
    RunPythonFileTool,
)
from vanna.tools.run_sql import RunSqlTool

FRAMEWORKS = ("fastapi", "flask")
USER_HEADERS = {"Authorization": "Bearer user"}
ADMIN_HEADERS = {"Authorization": "Bearer admin"}


class HeaderUserResolver(UserResolver):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def resolve_user(self, request_context: RequestContext) -> User:
        self.calls += 1
        if self.fail:
            raise RuntimeError("resolver TOP_SECRET")
        authorization = request_context.get_header("Authorization")
        if authorization == "Bearer admin":
            return User(
                id="admin-user",
                authenticated=True,
                group_memberships=["admin"],
            )
        if authorization == "Bearer user":
            return User(id="normal-user", authenticated=True)
        if authorization == "Bearer legacy":
            return User(id="legacy-default-user")
        return User(id="anonymous", authenticated=False)


class RevokingUserResolver(UserResolver):
    def __init__(self) -> None:
        self.calls = 0

    async def resolve_user(self, request_context: RequestContext) -> User:
        del request_context
        self.calls += 1
        if self.calls == 1:
            return User(id="normal-user", authenticated=True)
        raise RuntimeError("credential revoked TOP_SECRET")


class MalformedUserResolver(UserResolver):
    def __init__(self, *, tenant_id: Any = "tenant-a") -> None:
        self.tenant_id = tenant_id

    async def resolve_user(self, request_context: RequestContext) -> User:
        del request_context
        return User.model_construct(
            id="",
            authenticated=True,
            metadata={"tenant_id": self.tenant_id},
            group_memberships=["user"],
        )


class FakeConversationStore:
    def __init__(
        self,
        *,
        supports_atomic_ownership: bool,
        supports_atomic_updates: Optional[bool] = None,
    ) -> None:
        self.supports_atomic_ownership = supports_atomic_ownership
        self.supports_atomic_updates = (
            supports_atomic_ownership
            if supports_atomic_updates is None
            else supports_atomic_updates
        )

    async def claim_conversation(self, *_args: Any, **_kwargs: Any) -> Any:
        conversation_id = str(_args[0])
        user = _args[1]
        existing = await self.get_conversation(conversation_id, user)
        return (
            existing or Conversation(id=conversation_id, user=user, messages=[]),
            existing is None,
        )

    async def get_conversation(self, conversation_id: str, user: User) -> Any:
        if conversation_id == "foreign-conversation":
            raise ConversationAccessDeniedError("Conversation access denied")
        if conversation_id == "owned-conversation":
            return Conversation(
                id=conversation_id,
                user=user,
                messages=[
                    Message(
                        role="user",
                        content="original question",
                        metadata={REQUEST_ID_METADATA_KEY: "owned-request"},
                    )
                ],
            )
        return None


class FakeAgent:
    def __init__(
        self,
        *,
        resolver: Optional[UserResolver] = None,
        store_support: bool = True,
        failure: Optional[str] = None,
    ) -> None:
        self.user_resolver = resolver or HeaderUserResolver()
        self.conversation_store = FakeConversationStore(
            supports_atomic_ownership=store_support
        )
        self.agent_memory = SimpleAgentMemory()
        self.failure = failure
        self.chat_calls = 0

    async def send_message(self, **kwargs: Any) -> Any:
        self.chat_calls += 1
        await self.user_resolver.resolve_user(kwargs["request_context"])
        if self.failure:
            raise RuntimeError(self.failure)
        if False:
            yield None


class Snapshot(BaseModel):
    schema_hash: str = "hash-1"
    snapshot_id: str = "snapshot-1"
    schema_version: int = 2
    previous_snapshot_id: str = "snapshot-0"


class ServiceResult(BaseModel):
    status: str = "ok"


class FakeSchemaService:
    def __init__(self) -> None:
        self.latest_calls = 0
        self.sync_calls = 0
        self.latest_context: Optional[Any] = None

    async def get_latest_snapshot(self, context: Any) -> Snapshot:
        self.latest_calls += 1
        self.latest_context = context
        return Snapshot()

    async def sync(self, context: Any) -> ServiceResult:
        del context
        self.sync_calls += 1
        return ServiceResult()


class FakeFeedbackService:
    def __init__(self, *, conflict: bool = False) -> None:
        self.calls = 0
        self.review_list_calls = 0
        self.review_calls = 0
        self.export_calls = 0
        self.conflict = conflict

    async def process_feedback(self, feedback: Any, context: Any) -> ServiceResult:
        del feedback, context
        self.calls += 1
        return ServiceResult(status="accepted")

    async def list_review_queue(self, context: Any, **kwargs: Any) -> ServiceResult:
        del context, kwargs
        self.review_list_calls += 1
        return ServiceResult()

    async def review_feedback(
        self,
        feedback_id: str,
        review: Any,
        context: Any,
    ) -> ServiceResult:
        del feedback_id, review, context
        self.review_calls += 1
        if self.conflict:
            raise FeedbackStateError("already reviewed TOP_SECRET")
        return ServiceResult()

    async def approved_export(self, context: Any) -> ServiceResult:
        del context
        self.export_calls += 1
        return ServiceResult()


class PermissiveAuthorizer(RouteAuthorizer):
    def authorize(self, action: str, user: User, context: RequestContext) -> bool:
        del action, user, context
        return True


class RecordingAuthorizer(RouteAuthorizer):
    def __init__(self, *, allow: bool) -> None:
        self.allow = allow
        self.actions: list[str] = []

    def authorize(self, action: str, user: User, context: RequestContext) -> bool:
        del user, context
        self.actions.append(action)
        return self.allow


class MetadataAuthorizer(RouteAuthorizer):
    def authorize(self, action: str, user: User, context: RequestContext) -> bool:
        del action, user
        return context.metadata.get("deny") is not True


class RejectingLimiter:
    def __init__(self) -> None:
        self.user: Optional[User] = None
        self.remote_addr: Optional[str] = None
        self.metadata_user: Optional[User] = None

    def check(self, user: User, context: RequestContext) -> bool:
        self.user = user
        self.remote_addr = context.remote_addr
        candidate = context.metadata.get(RESOLVED_USER_METADATA_KEY)
        self.metadata_user = candidate if isinstance(candidate, User) else None
        return False


def make_client(
    framework: str, agent: FakeAgent, config: Optional[Dict[str, Any]] = None
) -> Any:
    if framework == "fastapi":
        fastapi_app = VannaFastAPIServer(
            agent,  # type: ignore[arg-type]
            config,
        ).create_app()
        return TestClient(fastapi_app, raise_server_exceptions=False)
    flask_app = VannaFlaskServer(agent, config).create_app()  # type: ignore[arg-type]
    return flask_app.test_client()


def response_json(response: Any) -> Dict[str, Any]:
    value = response.json() if callable(response.json) else response.json
    assert isinstance(value, dict)
    return value


def assert_public_error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status
    payload = response_json(response)
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == code
    assert payload["error"]["correlation_id"].startswith("err_")
    assert set(payload["error"]) == {
        "code",
        "message",
        "correlation_id",
        "retryable",
    }


def test_user_authentication_default_is_compatible_but_basic_resolver_is_anonymous() -> (
    None
):
    user = User(id="legacy")
    assert user.authenticated is True
    assert "authenticated" not in user.model_fields_set

    import asyncio

    anonymous = asyncio.run(SimpleUserResolver().resolve_user(RequestContext()))
    assert anonymous.authenticated is False
    assert "authenticated" in anonymous.model_fields_set


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_production_defaults_keep_health_public_and_disable_ui_and_cors(
    framework: str,
) -> None:
    client = make_client(framework, FakeAgent())

    assert response_json(client.get("/health")) == {
        "status": "healthy",
        "service": "vanna",
    }
    assert client.get("/").status_code == 404
    response = client.get("/health", headers={"Origin": "https://attacker.invalid"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_production_rejects_non_atomic_conversation_stores(framework: str) -> None:
    agent = FakeAgent(store_support=False)
    with pytest.raises(ValueError, match="supports_atomic_ownership=True"):
        make_client(framework, agent)

    agent.conversation_store = FakeConversationStore(
        supports_atomic_ownership=True,
        supports_atomic_updates=False,
    )
    with pytest.raises(ValueError, match="supports_atomic_updates=True"):
        make_client(framework, agent)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_production_rejects_agent_memory_without_tenant_isolation(
    framework: str,
) -> None:
    agent = FakeAgent()
    agent.agent_memory.supports_tenant_isolation = False

    with pytest.raises(ValueError, match="supports_tenant_isolation=True"):
        make_client(framework, agent)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_development_allows_legacy_agent_memory(framework: str) -> None:
    agent = FakeAgent()
    agent.agent_memory.supports_tenant_isolation = False

    client = make_client(framework, agent, {"security_mode": "development"})

    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_unauthenticated_routes_are_401_before_side_effects(framework: str) -> None:
    agent = FakeAgent()
    schema_service = FakeSchemaService()
    feedback_service = FakeFeedbackService()
    client = make_client(
        framework,
        agent,
        {
            "schema_sync_service": schema_service,
            "feedback_service": feedback_service,
        },
    )

    responses = [
        client.post("/api/vanna/v2/chat_poll", json={"message": "hello"}),
        client.post(
            "/api/vanna/v3/feedback",
            json={
                "rating": "up",
                "conversation_id": "owned-conversation",
                "request_id": "owned-request",
            },
        ),
        client.get("/api/vanna/v3/schema/status"),
        client.post("/api/vanna/v3/schema/sync"),
        client.get("/api/vanna/v3/feedback/review"),
        client.get("/api/vanna/v3/feedback/export"),
    ]
    for response in responses:
        assert_public_error(response, 401, "authentication_required")

    assert agent.chat_calls == 0
    assert schema_service.latest_calls == 0
    assert schema_service.sync_calls == 0
    assert feedback_service.calls == 0
    assert feedback_service.review_list_calls == 0
    assert feedback_service.export_calls == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_production_does_not_trust_implicit_authenticated_default(
    framework: str,
) -> None:
    client = make_client(
        framework,
        FakeAgent(),
        {"route_authorizer": PermissiveAuthorizer()},
    )
    response = client.post(
        "/api/vanna/v2/chat_poll",
        json={"message": "hello"},
        headers={"Authorization": "Bearer legacy"},
    )
    assert_public_error(response, 401, "authentication_required")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_production_rejects_malformed_authenticated_principals(
    framework: str,
) -> None:
    client = make_client(
        framework,
        FakeAgent(resolver=MalformedUserResolver()),
        {"route_authorizer": PermissiveAuthorizer()},
    )

    response = client.post(
        "/api/vanna/v2/chat_poll",
        json={"message": "hello"},
        headers=USER_HEADERS,
    )

    assert_public_error(response, 401, "authentication_required")


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_authorized_v2_poll_payload_and_custom_prefix_are_preserved(
    framework: str,
) -> None:
    resolver = HeaderUserResolver()
    agent = FakeAgent(resolver=resolver)
    client = make_client(
        framework,
        agent,
        {"api_v2_prefix": "/custom/v2", "api_v3_prefix": "/custom/v3"},
    )

    assert (
        client.post(
            "/api/vanna/v2/chat_poll", json={"message": "hello"}, headers=USER_HEADERS
        ).status_code
        == 404
    )
    response = client.post(
        "/custom/v2/chat_poll", json={"message": "hello"}, headers=USER_HEADERS
    )
    assert response.status_code == 200
    assert response_json(response) == {
        "chunks": [],
        "conversation_id": "",
        "request_id": "",
        "total_chunks": 0,
    }
    assert agent.chat_calls == 1
    assert resolver.calls == 1


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_schema_requires_admin_and_feedback_requires_authentication(
    framework: str,
) -> None:
    schema_service = FakeSchemaService()
    feedback_service = FakeFeedbackService()
    client = make_client(
        framework,
        FakeAgent(),
        {
            "api_v3_prefix": "/tenant/v3",
            "schema_sync_service": schema_service,
            "feedback_service": feedback_service,
        },
    )

    denied = client.get("/tenant/v3/schema/status", headers=USER_HEADERS)
    assert_public_error(denied, 403, "route_access_denied")
    assert schema_service.latest_calls == 0

    status = client.get("/tenant/v3/schema/status", headers=ADMIN_HEADERS)
    assert status.status_code == 200
    assert response_json(status)["snapshot"]["schema_hash"] == "hash-1"
    assert schema_service.latest_context.user.id == "admin-user"

    sync = client.post("/tenant/v3/schema/sync", headers=ADMIN_HEADERS)
    assert sync.status_code == 200
    assert schema_service.sync_calls == 1

    feedback = client.post(
        "/tenant/v3/feedback",
        json={
            "rating": "up",
            "conversation_id": "owned-conversation",
            "request_id": "owned-request",
        },
        headers=USER_HEADERS,
    )
    assert feedback.status_code == 200
    assert feedback_service.calls == 1

    denied_review = client.get("/tenant/v3/feedback/review", headers=USER_HEADERS)
    assert_public_error(denied_review, 403, "route_access_denied")
    denied_export = client.get("/tenant/v3/feedback/export", headers=USER_HEADERS)
    assert_public_error(denied_export, 403, "route_access_denied")

    review_queue = client.get(
        "/tenant/v3/feedback/review",
        headers=ADMIN_HEADERS,
    )
    reviewed = client.post(
        "/tenant/v3/feedback/fb_1/review",
        json={"status": "approved"},
        headers=ADMIN_HEADERS,
    )
    exported = client.get("/tenant/v3/feedback/export", headers=ADMIN_HEADERS)
    assert review_queue.status_code == 200
    assert reviewed.status_code == 200
    assert exported.status_code == 200
    assert feedback_service.review_list_calls == 1
    assert feedback_service.review_calls == 1
    assert feedback_service.export_calls == 1


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_feedback_policy_ownership_and_review_conflicts_are_public(
    framework: str,
    tmp_path: Path,
) -> None:
    real_feedback = FeedbackService(database_path=str(tmp_path / "feedback.sqlite3"))
    client = make_client(
        framework,
        FakeAgent(),
        {"feedback_service": real_feedback},
    )

    unsafe = client.post(
        "/api/vanna/v3/feedback",
        json={
            "rating": "down",
            "conversation_id": "owned-conversation",
            "request_id": "owned-request",
            "question": "Delete data",
            "corrected_sql": "DROP TABLE customers",
        },
        headers=USER_HEADERS,
    )
    assert_public_error(unsafe, 400, "invalid_request")

    foreign = client.post(
        "/api/vanna/v3/feedback",
        json={
            "rating": "up",
            "conversation_id": "foreign-conversation",
            "request_id": "owned-request",
        },
        headers=USER_HEADERS,
    )
    assert_public_error(foreign, 403, "route_access_denied")

    missing = client.post(
        "/api/vanna/v3/feedback",
        json={
            "rating": "up",
            "conversation_id": "missing-conversation",
            "request_id": "owned-request",
        },
        headers=USER_HEADERS,
    )
    forged_request = client.post(
        "/api/vanna/v3/feedback",
        json={
            "rating": "up",
            "conversation_id": "owned-conversation",
            "request_id": "forged-request",
        },
        headers=USER_HEADERS,
    )
    assert_public_error(missing, 403, "route_access_denied")
    assert_public_error(forged_request, 403, "route_access_denied")

    conflict_service = FakeFeedbackService(conflict=True)
    conflict_client = make_client(
        framework,
        FakeAgent(),
        {"feedback_service": conflict_service},
    )
    conflict = conflict_client.post(
        "/api/vanna/v3/feedback/fb_1/review",
        json={"status": "approved"},
        headers=ADMIN_HEADERS,
    )
    assert_public_error(conflict, 409, "request_conflict")
    assert "TOP_SECRET" not in str(conflict.text)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_injected_authorizer_denial_is_403_before_chat(framework: str) -> None:
    authorizer = RecordingAuthorizer(allow=False)
    agent = FakeAgent()
    client = make_client(framework, agent, {"route_authorizer": authorizer})

    response = client.post(
        "/api/vanna/v2/chat_poll", json={"message": "hello"}, headers=USER_HEADERS
    )
    assert_public_error(response, 403, "route_access_denied")
    assert authorizer.actions == [CHAT_EXECUTE]
    assert agent.chat_calls == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("malformed", (0, "allow", {"allow": True}))
def test_malformed_authorizer_decision_fails_closed(
    framework: str,
    malformed: Any,
) -> None:
    class MalformedAuthorizer(RouteAuthorizer):
        def authorize(
            self,
            action: str,
            user: User,
            context: RequestContext,
        ) -> Any:
            del action, user, context
            return malformed

    agent = FakeAgent()
    client = make_client(
        framework,
        agent,
        {"route_authorizer": MalformedAuthorizer()},
    )
    response = client.post(
        "/api/vanna/v2/chat_poll",
        json={"message": "hello"},
        headers=USER_HEADERS,
    )

    assert_public_error(response, 403, "route_access_denied")
    assert agent.chat_calls == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_rate_limiter_rejection_is_429_with_trusted_user_context(
    framework: str,
) -> None:
    limiter = RejectingLimiter()
    client = make_client(framework, FakeAgent(), {"rate_limiter": limiter})

    response = client.post(
        "/api/vanna/v2/chat_poll",
        json={"message": "hello"},
        headers={**USER_HEADERS, "X-Forwarded-For": "203.0.113.99"},
    )
    assert_public_error(response, 429, "rate_limit_exceeded")
    assert limiter.user is not None and limiter.user.id == "normal-user"
    assert limiter.metadata_user is limiter.user
    assert limiter.remote_addr != "203.0.113.99"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_builtin_limiter_ignores_spoofed_forwarded_addresses(framework: str) -> None:
    client = make_client(
        framework,
        FakeAgent(),
        {"rate_limiter": FixedWindowRateLimiter(requests_per_minute=1)},
    )
    first = client.post(
        "/api/vanna/v2/chat_poll",
        json={"message": "first"},
        headers={**USER_HEADERS, "X-Forwarded-For": "198.51.100.1"},
    )
    second = client.post(
        "/api/vanna/v2/chat_poll",
        json={"message": "second"},
        headers={**USER_HEADERS, "X-Forwarded-For": "198.51.100.2"},
    )
    assert first.status_code == 200
    assert_public_error(second, 429, "rate_limit_exceeded")


def test_builtin_limiter_uses_collision_safe_principal_scope() -> None:
    limiter = FixedWindowRateLimiter(requests_per_minute=1)
    context = RequestContext(remote_addr="127.0.0.1")
    first = User(id="c", metadata={"tenant_id": "a:b"})
    second = User(id="b:c", metadata={"tenant_id": "a"})

    limiter.check(first, context)
    limiter.check(second, context)

    with pytest.raises(RateLimitExceededError) as error:
        limiter.check(first, context)
    assert getattr(error.value, "code", None) == "rate_limit_exceeded"


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize(
    "path",
    (
        "/api/vanna/v2/chat_poll",
        "/api/vanna/v3/chat/poll",
        "/api/vanna/v3/chat/events",
    ),
)
def test_foreign_conversation_is_denied_before_stream_execution(
    framework: str,
    path: str,
) -> None:
    agent = FakeAgent()
    client = make_client(framework, agent)

    response = client.post(
        path,
        json={"message": "hello", "conversation_id": "foreign-conversation"},
        headers=USER_HEADERS,
    )

    assert_public_error(response, 403, "conversation_access_denied")
    assert agent.chat_calls == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize(
    "metadata",
    (
        {"schema_hash": "forged"},
        {"_vanna_schema_lineage": {"schema_hash": "forged"}},
        {f"field_{index}": "x" * 4096 for index in range(20)},
        {
            "level": {
                "level": {
                    "level": {
                        "level": {
                            "level": {
                                "level": {"level": {"level": {"level": "too-deep"}}}
                            }
                        }
                    }
                }
            }
        },
    ),
)
def test_public_chat_metadata_is_bounded_and_cannot_forge_lineage(
    framework: str,
    metadata: Dict[str, Any],
) -> None:
    agent = FakeAgent()
    client = make_client(framework, agent)

    response = client.post(
        "/api/vanna/v3/chat/poll",
        json={"message": "hello", "metadata": metadata},
        headers=USER_HEADERS,
    )

    assert_public_error(response, 400, "invalid_request")
    assert agent.chat_calls == 0


def test_production_installs_a_bounded_default_rate_limiter() -> None:
    limiter = configured_rate_limiter({}, security_mode="production")
    assert isinstance(limiter, FixedWindowRateLimiter)
    assert limiter.requests_per_minute == 120
    assert configured_rate_limiter({}, security_mode="development") is None
    with pytest.raises(ValueError, match="must be an integer"):
        configured_rate_limiter(
            {"rate_limit_requests_per_minute": True},
            security_mode="production",
        )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_legacy_request_guard_permission_error_maps_to_429(framework: str) -> None:
    def guard(chat_request: Any, request_context: RequestContext) -> None:
        del chat_request, request_context
        raise PermissionError("guard TOP_SECRET")

    client = make_client(framework, FakeAgent(), {"request_guard": guard})
    response = client.post(
        "/api/vanna/v2/chat_poll", json={"message": "hello"}, headers=USER_HEADERS
    )
    assert_public_error(response, 429, "rate_limit_exceeded")
    assert "TOP_SECRET" not in response.text


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_invalid_and_internal_errors_are_stable_and_redacted(framework: str) -> None:
    client = make_client(framework, FakeAgent(failure="agent TOP_SECRET"))

    invalid = client.post("/api/vanna/v2/chat_poll", json={}, headers=USER_HEADERS)
    assert_public_error(invalid, 400, "invalid_request")

    failed = client.post(
        "/api/vanna/v2/chat_poll", json={"message": "hello"}, headers=USER_HEADERS
    )
    assert_public_error(failed, 500, "internal_error")
    assert "TOP_SECRET" not in failed.text

    stream = client.post(
        "/api/vanna/v2/chat_sse", json={"message": "hello"}, headers=USER_HEADERS
    )
    assert stream.status_code == 200
    assert "TOP_SECRET" not in stream.text
    assert "An unexpected error occurred." in stream.text


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_malformed_request_validation_precedes_authentication(framework: str) -> None:
    """Keep validation precedence explicit without invoking agent side effects."""

    agent = FakeAgent()
    response = make_client(framework, agent).post("/api/vanna/v2/chat_poll", json={})
    assert_public_error(response, 400, "invalid_request")
    assert agent.chat_calls == 0


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_explicit_ui_and_exact_credentialed_cors_can_be_enabled(
    framework: str,
) -> None:
    if framework == "fastapi":
        cors = {
            "enabled": True,
            "allow_origins": ["https://ui.example"],
            "allow_credentials": True,
        }
    else:
        cors = {
            "enabled": True,
            "origins": ["https://ui.example"],
            "supports_credentials": True,
        }
    client = make_client(
        framework,
        FakeAgent(),
        {"enable_default_ui_route": True, "cors": cors},
    )

    assert_public_error(client.get("/"), 401, "authentication_required")
    ui_response = client.get("/", headers=USER_HEADERS)
    assert ui_response.status_code == 200
    assert ui_response.headers["content-type"].startswith("text/html")
    assert ui_response.headers["x-content-type-options"] == "nosniff"
    assert ui_response.headers["x-frame-options"] == "DENY"
    assert ui_response.headers["referrer-policy"] == "no-referrer"
    csp = ui_response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp

    page = ui_response.text
    assert page.count("<script") == 1
    assert 'src="/static/vanna-components.js"' in page
    assert 'api-version="v2"' in page
    assert 'protocol="v2"' in page
    for active_content in (
        "https://",
        "http://",
        "javascript:",
        "window.open",
        "document.write",
        "document.cookie",
        "tailwind.config",
    ):
        assert active_content not in page

    response = client.get("/health", headers={"Origin": "https://ui.example"})
    assert response.headers["access-control-allow-origin"] == "https://ui.example"
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_credentialed_wildcard_cors_is_rejected(framework: str) -> None:
    if framework == "fastapi":
        cors = {
            "enabled": True,
            "allow_origins": ["*"],
            "allow_credentials": True,
        }
    else:
        cors = {
            "enabled": True,
            "origins": "*",
            "supports_credentials": True,
        }
    with pytest.raises(ValueError, match="wildcard"):
        make_client(framework, FakeAgent(), {"cors": cors})


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_credentialed_regex_cors_is_rejected(framework: str) -> None:
    cors = (
        {
            "enabled": True,
            "allow_origins": [],
            "allow_origin_regex": r"https?://.*",
            "allow_credentials": True,
        }
        if framework == "fastapi"
        else {
            "enabled": True,
            "origins": r"https?://.*",
            "supports_credentials": True,
        }
    )

    with pytest.raises(ValueError, match="explicit origins"):
        make_client(framework, FakeAgent(), {"cors": cors})


@pytest.mark.asyncio
async def test_audit_serialization_failure_redacts_exception(caplog: Any) -> None:
    secret = "postgresql://svc:TOP_SECRET@db.internal/app"

    class ExplodingAuditEvent(AuditEvent):
        def model_dump(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            del args, kwargs
            raise RuntimeError(secret)

    event = ExplodingAuditEvent(
        event_type=AuditEventType.MESSAGE_RECEIVED,
        user_id="user-1",
        conversation_id="conv-1",
        request_id="req-1",
    )

    with caplog.at_level("ERROR"):
        await LoggingAuditLogger().log_event(event)

    assert secret not in caplog.text
    assert "Traceback" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


def test_audit_parameter_sanitization_is_recursive_and_hides_sql() -> None:
    sanitized, changed = LoggingAuditLogger()._sanitize_parameters(
        {
            "sql": "SELECT * FROM t WHERE api_key='TOP_SECRET'",
            "payload": {
                "token": "NESTED_SECRET",
                "note": "password=EMBEDDED_SECRET",
                "safe": 7,
            },
        }
    )

    assert changed is True
    assert sanitized == {
        "sql": "[REDACTED]",
        "payload": {
            "token": "[REDACTED]",
            "note": "[REDACTED]",
            "safe": 7,
        },
    }
    assert "TOP_SECRET" not in str(sanitized)
    assert "NESTED_SECRET" not in str(sanitized)


@pytest.mark.asyncio
async def test_provider_logging_omits_payloads_responses_and_exception_values(
    caplog: Any,
    capsys: Any,
) -> None:
    secret = "provider-TOP_SECRET"

    class AnthropicMessages:
        def create(self, **payload: Any) -> Any:
            del payload
            return type(
                "Response",
                (),
                {"stop_reason": "stop", "usage": None, "secret": secret},
            )()

    anthropic = object.__new__(AnthropicLlmService)
    anthropic.model = "safe-model"
    anthropic._client = type("Client", (), {"messages": AnthropicMessages()})()
    anthropic._build_payload = lambda request: {  # type: ignore[method-assign]
        "messages": [{"content": secret}],
        "tools": [],
    }
    anthropic._parse_message_content = lambda response: (  # type: ignore[method-assign]
        secret,
        [],
    )

    gemini = object.__new__(GeminiLlmService)
    gemini.model_name = "safe-model"
    gemini._build_payload = lambda request: ([secret], object())  # type: ignore[method-assign]

    class GeminiModels:
        def generate_content(self, **payload: Any) -> Any:
            del payload
            raise RuntimeError(secret)

    gemini._client = type("Client", (), {"models": GeminiModels()})()

    openai = object.__new__(OpenAIResponsesService)
    openai.model = "safe-model"

    class OpenAIResponse:
        id = "response-id"
        output_text = secret
        output: list[Any] = []
        status = "completed"
        usage = None

    class OpenAIStream:
        def __init__(self) -> None:
            self.emitted = False

        async def __aenter__(self) -> "OpenAIStream":
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args

        def __aiter__(self) -> "OpenAIStream":
            return self

        async def __anext__(self) -> Any:
            if self.emitted:
                raise StopAsyncIteration
            self.emitted = True
            return type(
                "Event",
                (),
                {"type": "response.output_text.delta", "delta": secret},
            )()

        async def get_final_response(self) -> OpenAIResponse:
            return OpenAIResponse()

    class OpenAIResponses:
        async def create(self, **payload: Any) -> OpenAIResponse:
            del payload
            return OpenAIResponse()

        def stream(self, **payload: Any) -> OpenAIStream:
            del payload
            return OpenAIStream()

    openai.client = type("Client", (), {"responses": OpenAIResponses()})()

    request = LlmRequest(user=User(id="u"), messages=[])
    with caplog.at_level("DEBUG"):
        await anthropic.send_request(request)
        with pytest.raises(RuntimeError, match="TOP_SECRET"):
            await gemini.send_request(request)
        await openai.send_request(request)
        _ = [chunk async for chunk in openai.stream_request(request)]

    assert secret not in caplog.text
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_development_allows_legacy_store_but_requires_explicit_policy(
    framework: str,
) -> None:
    agent = FakeAgent(resolver=SimpleUserResolver(), store_support=False)
    client = make_client(
        framework,
        agent,
        {
            "security_mode": "development",
            "route_authorizer": PermissiveAuthorizer(),
        },
    )
    response = client.post("/api/vanna/v2/chat_poll", json={"message": "hello"})
    assert response.status_code == 200


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_development_run_rejects_non_loopback_host(framework: str) -> None:
    config = {
        "security_mode": "development",
        "route_authorizer": PermissiveAuthorizer(),
    }
    if framework == "fastapi":
        server: Any = VannaFastAPIServer(FakeAgent(), config)  # type: ignore[arg-type]
    else:
        server = VannaFlaskServer(FakeAgent(), config)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="loopback"):
        server.run(host="0.0.0.0")


def test_fastapi_development_run_defaults_to_loopback(monkeypatch: Any) -> None:
    captured: Dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        del app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    server = VannaFastAPIServer(
        FakeAgent(),  # type: ignore[arg-type]
        {
            "security_mode": "development",
            "route_authorizer": PermissiveAuthorizer(),
        },
    )
    server.run()
    assert captured["host"] == "127.0.0.1"


def test_flask_development_run_defaults_to_loopback(monkeypatch: Any) -> None:
    captured: Dict[str, Any] = {}

    def fake_run(self: Flask, **kwargs: Any) -> None:
        del self
        captured.update(kwargs)

    monkeypatch.setattr(Flask, "run", fake_run)
    server = VannaFlaskServer(
        FakeAgent(),  # type: ignore[arg-type]
        {
            "security_mode": "development",
            "route_authorizer": PermissiveAuthorizer(),
        },
    )
    server.run()
    assert captured["host"] == "127.0.0.1"


def test_fastapi_websocket_authenticates_and_authorizes_before_accept() -> None:
    resolver = HeaderUserResolver()
    agent = FakeAgent(resolver=resolver)
    client = make_client("fastapi", agent)

    with pytest.raises(WebSocketDisconnect) as unauthenticated:
        with client.websocket_connect("/api/vanna/v2/chat_websocket"):
            pass
    assert unauthenticated.value.code == 4401
    assert agent.chat_calls == 0

    authorizer = RecordingAuthorizer(allow=False)
    denied_client = make_client(
        "fastapi", FakeAgent(), {"route_authorizer": authorizer}
    )
    with pytest.raises(WebSocketDisconnect) as forbidden:
        with denied_client.websocket_connect(
            "/api/vanna/v2/chat_websocket", headers=USER_HEADERS
        ):
            pass
    assert forbidden.value.code == 4403
    assert authorizer.actions == [CHAT_EXECUTE]


def test_fastapi_websocket_preserves_authorized_completion_and_redacts_errors() -> None:
    agent = FakeAgent()
    client = make_client("fastapi", agent)

    with client.websocket_connect(
        "/api/vanna/v2/chat_websocket", headers=USER_HEADERS
    ) as websocket:
        websocket.send_json({"metadata": "request TOP_SECRET"})
        invalid = websocket.receive_json()
        assert invalid == {
            "type": "error",
            "data": {"message": "An unexpected error occurred."},
        }

        websocket.send_json(
            {"message": "hello", "conversation_id": "c1", "request_id": "r1"}
        )
        assert websocket.receive_json() == {
            "type": "completion",
            "data": {"status": "done"},
            "conversation_id": "",
            "request_id": "",
        }
    assert agent.chat_calls == 1


def test_fastapi_websocket_rate_limits_each_chat_message() -> None:
    agent = FakeAgent()
    client = make_client(
        "fastapi",
        agent,
        {"rate_limiter": FixedWindowRateLimiter(requests_per_minute=1)},
    )

    with client.websocket_connect(
        "/api/vanna/v2/chat_websocket", headers=USER_HEADERS
    ) as websocket:
        websocket.send_json({"message": "first"})
        assert websocket.receive_json()["type"] == "completion"

        websocket.send_json({"message": "second"})
        assert websocket.receive_json() == {
            "type": "error",
            "data": {"message": "The request rate limit was exceeded."},
        }

    assert agent.chat_calls == 1


def test_fastapi_websocket_reauthorizes_each_chat_message() -> None:
    agent = FakeAgent()
    client = make_client("fastapi", agent, {"route_authorizer": MetadataAuthorizer()})

    with client.websocket_connect(
        "/api/vanna/v2/chat_websocket", headers=USER_HEADERS
    ) as websocket:
        websocket.send_json({"message": "blocked", "metadata": {"deny": True}})
        assert websocket.receive_json() == {
            "type": "error",
            "data": {"message": "Access to this route is denied."},
        }

    assert agent.chat_calls == 0


def test_fastapi_websocket_reauthenticates_each_chat_message() -> None:
    resolver = RevokingUserResolver()
    agent = FakeAgent(resolver=resolver)
    client = make_client("fastapi", agent)

    with client.websocket_connect(
        "/api/vanna/v2/chat_websocket", headers=USER_HEADERS
    ) as websocket:
        websocket.send_json({"message": "credentials are now revoked"})
        assert websocket.receive_json() == {
            "type": "error",
            "data": {"message": "Authentication is required."},
        }

    assert resolver.calls == 2
    assert agent.chat_calls == 0


def test_fastapi_websocket_resolver_exception_is_redacted_pre_accept() -> None:
    client = make_client("fastapi", FakeAgent(resolver=HeaderUserResolver(fail=True)))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/vanna/v2/chat_websocket"):
            pass
    assert exc_info.value.code == 4401
    assert "TOP_SECRET" not in str(exc_info.value)


def test_flask_websocket_remains_explicit_501_without_fake_upgrade() -> None:
    client = make_client("flask", FakeAgent())
    assert_public_error(
        client.get("/api/vanna/v2/chat_websocket"),
        401,
        "authentication_required",
    )

    response = client.get("/api/vanna/v2/chat_websocket", headers=USER_HEADERS)
    assert response.status_code == 501
    assert response_json(response)["suggestion"].startswith("Use Flask-SocketIO")


def test_server_startup_never_installs_runtime_dependencies() -> None:
    root = Path(__file__).parents[1]
    source = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "src/vanna/servers/fastapi/app.py",
            "src/vanna/servers/flask/app.py",
        )
    )

    assert "subprocess" not in source
    assert 'pip", "install' not in source
    assert "check_call" not in source


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize(
    "unsafe_config",
    [
        {"cdn_url": "https://cdn.example/vanna-components.js"},
        {"component_script_path": "/static/%22%3E%3Cscript%3E"},
        {"api_base_url": "/gateway/%2e%2e/admin"},
        {"api_base_url": "/gateway?target=admin"},
    ],
)
def test_bundled_ui_rejects_unsafe_asset_and_api_paths(
    framework: str,
    unsafe_config: Dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="same-origin|dot path"):
        make_client(
            framework,
            FakeAgent(),
            {"enable_default_ui_route": True, **unsafe_config},
        )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_bundled_ui_accepts_and_escapes_same_origin_configuration(
    framework: str,
) -> None:
    client = make_client(
        framework,
        FakeAgent(),
        {
            "enable_default_ui_route": True,
            "component_script_path": "/assets/vanna.js?build=3&channel=stable",
            "api_base_url": "/gateway",
        },
    )

    response = client.get("/", headers=USER_HEADERS)

    assert response.status_code == 200
    assert 'src="/assets/vanna.js?build=3&amp;channel=stable"' in response.text
    assert 'api-base="/gateway"' in response.text
    assert 'sse-endpoint="/gateway/api/vanna/v2/chat_sse"' in response.text
    assert "https://" not in response.text


def test_public_examples_do_not_reintroduce_executable_artifact_guidance() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    artifact_example = (root / "src/vanna/examples/artifact_example.py").read_text(
        encoding="utf-8"
    )
    minimal_example = (root / "src/vanna/examples/minimal_example.py").read_text(
        encoding="utf-8"
    )
    coding_example = (root / "src/vanna/examples/coding_agent_example.py").read_text(
        encoding="utf-8"
    )

    assert "img.vanna.ai" not in readme
    assert 'src="/assets/vanna-components.js"' in readme
    for executable_pattern in (
        "<script",
        "onclick=",
        "window.open",
        "document.write",
        "create_d3",
    ):
        assert executable_pattern not in artifact_example
    assert "RunPythonFileTool" not in minimal_example
    assert "PipInstallTool" not in minimal_example
    assert "create_python_tools" not in coding_example
    assert "run_python_file" not in coding_example


class _ExplodingExecutionService:
    async def run_bash(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("disabled core tools must never invoke a command service")


class _RenamedPythonTool(RunPythonFileTool):
    @property
    def name(self) -> str:
        return "renamed_executor"


class _ExplodingArbitraryTool(_RenamedPythonTool):
    async def execute(
        self, context: ToolContext, args: RunPythonFileArgs
    ) -> ToolResult:
        del context, args
        raise AssertionError("forbidden registry tool must never execute")


class _ExplodingWritableRunner:
    dialect = "sqlite"
    native_read_only = False

    def __init__(self) -> None:
        self.calls = 0

    async def run_sql(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("production must reject writable SQL before execution")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    (
        (
            RunPythonFileTool(_ExplodingExecutionService()),  # type: ignore[arg-type]
            RunPythonFileArgs(filename="model_generated.py"),
        ),
        (
            PipInstallTool(_ExplodingExecutionService()),  # type: ignore[arg-type]
            PipInstallArgs(packages=["attacker-package"]),
        ),
    ),
)
async def test_builtin_python_tools_are_inert_compatibility_shims(
    tool: Any,
    args: Any,
) -> None:
    context = ToolContext(
        user=User(id="admin", group_memberships=["admin"]),
        conversation_id="conversation",
        request_id="request",
        agent_memory=SimpleAgentMemory(),
    )

    result = await tool.execute(context, args)

    assert result.success is False
    assert result.metadata == {"code": "code_execution_disabled"}
    assert "disabled in Vanna v3" in result.result_for_llm
    assert ARBITRARY_CODE_EXECUTION_CAPABILITY in tool.capabilities


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize(
    "tool",
    (RunPythonFileTool(), PipInstallTool(), _RenamedPythonTool()),
)
def test_production_rejects_wrapped_arbitrary_execution_tools(
    framework: str,
    tool: Any,
) -> None:
    registry = ToolRegistry()
    registry.register_local_tool(tool, access_groups=["admin"])
    agent = FakeAgent()
    agent.tool_registry = registry

    with pytest.raises(ValueError, match="arbitrary code execution"):
        make_client(framework, agent)


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("custom_name", (None, "renamed_writable_sql"))
def test_production_rejects_wrapped_writable_sql_tools(
    framework: str,
    custom_name: Optional[str],
) -> None:
    runner = _ExplodingWritableRunner()
    tool = RunSqlTool(
        runner,  # type: ignore[arg-type]
        custom_tool_name=custom_name,
        read_only=False,
    )
    assert PRIVILEGED_SQL_WRITE_CAPABILITY in tool.capabilities
    registry = ToolRegistry()
    registry.register_local_tool(tool, access_groups=["admin"])
    agent = FakeAgent()
    agent.tool_registry = registry

    with pytest.raises(ValueError, match="privileged SQL write"):
        make_client(framework, agent)

    assert runner.calls == 0


def test_fastapi_websocket_claims_foreign_conversation_before_execution() -> None:
    agent = FakeAgent()
    client = make_client("fastapi", agent)

    with client.websocket_connect(
        "/api/vanna/v2/chat_websocket", headers=USER_HEADERS
    ) as websocket:
        websocket.send_json(
            {
                "message": "attempt takeover",
                "conversation_id": "foreign-conversation",
            }
        )
        assert websocket.receive_json() == {
            "type": "error",
            "data": {"message": "Access to this conversation is denied."},
        }

    assert agent.chat_calls == 0


@pytest.mark.asyncio
async def test_registry_never_advertises_or_executes_arbitrary_capability() -> None:
    registry = ToolRegistry()
    registry.register_local_tool(_ExplodingArbitraryTool(), access_groups=["admin"])
    context = ToolContext(
        user=User(id="admin", group_memberships=["admin"]),
        conversation_id="conversation",
        request_id="request",
        agent_memory=SimpleAgentMemory(),
    )

    assert await registry.list_tools() == []
    assert await registry.get_schemas(context.user) == []
    assert (
        await registry.get_authorized_tool_for_hooks("renamed_executor", context)
        is None
    )
    result = await registry.execute(
        ToolCall(
            id="forbidden-call",
            name="renamed_executor",
            arguments={"filename": "model_generated.py"},
        ),
        context,
    )

    assert result.success is False
    assert result.metadata == {"code": "code_execution_disabled"}
