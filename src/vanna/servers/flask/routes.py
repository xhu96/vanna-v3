"""Flask route implementations for Vanna Agents."""

import inspect
import json
import logging
import uuid
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    Generator,
    Optional,
)

from flask import Flask, Response, jsonify, request

from ...capabilities.schema_catalog import get_latest_snapshot_compat
from ...core.storage import ConversationAccessDeniedError, REQUEST_ID_METADATA_KEY
from ...core.tool import ToolContext
from ...core.user import (
    RequestContext,
    TRUSTED_SCHEMA_LINEAGE_METADATA_KEY,
    User,
)
from ...security.sql_policy import SqlPolicyViolation
from ...services.feedback import FeedbackRequest, FeedbackReviewRequest
from ...services.feedback_store import FeedbackStateError
from ..base import ChatHandler, ChatRequest
from ..base.authorization import (
    CHAT_EXECUTE,
    FEEDBACK_CREATE,
    FEEDBACK_EXPORT,
    FEEDBACK_REVIEW,
    SCHEMA_READ,
    SCHEMA_SYNC,
    UI_READ,
    attach_resolved_user,
    resolve_and_authorize,
)
from ..base.errors import (
    ConversationRouteAccessDeniedError,
    InternalServerError,
    InvalidRequestError,
    PublicServerError,
    RateLimitExceededError,
    RequestConflictError,
    RouteAccessDeniedError,
    ServiceNotConfiguredError,
)
from ..base.events_v3 import (
    collect_v3_poll,
    format_sse_event,
    iter_v3_events,
    prepare_v3_request,
)
from ..base.rate_limit import configured_rate_limiter, enforce_rate_limit
from ..base.security import route_authorizer, security_mode
from ..base.templates import (
    bundled_ui_security_headers,
    get_index_html,
)
from ._async import iter_async, run_async

logger = logging.getLogger(__name__)


def register_chat_routes(
    app: Flask, chat_handler: ChatHandler, config: Optional[Dict[str, Any]] = None
) -> None:
    """Register authenticated V2/V3 chat and service routes."""

    config = config or {}
    mode = security_mode(config)
    v2_prefix = config.get("api_v2_prefix", "/api/vanna/v2")
    v3_prefix = config.get("api_v3_prefix", "/api/vanna/v3")
    ui_enabled = bool(config.get("enable_default_ui_route", False))
    authorizer = route_authorizer(config, mode=mode, default_ui_enabled=ui_enabled)
    rate_limiter = configured_rate_limiter(config, security_mode=mode)
    request_guard: Optional[Callable[[ChatRequest, RequestContext], Any]] = config.get(
        "request_guard"
    )

    async def _await_guard(result: Awaitable[Any]) -> Any:
        return await result

    def _run_request_guard(
        chat_request: ChatRequest, request_context: RequestContext
    ) -> None:
        if request_guard is None:
            return
        try:
            result = request_guard(chat_request, request_context)
            if inspect.isawaitable(result):
                result = run_async(_await_guard(result))
        except RateLimitExceededError:
            raise
        except PermissionError as exc:
            raise RateLimitExceededError() from exc
        except PublicServerError:
            raise
        except Exception as exc:
            status_code = getattr(exc, "status_code", getattr(exc, "code", None))
            if status_code == 429:
                raise RateLimitExceededError() from exc
            raise InternalServerError() from exc
        if result is False:
            raise RateLimitExceededError()

    def _authorize(
        action: str,
        request_context: RequestContext,
        guard_request: Optional[ChatRequest] = None,
    ) -> User:
        user = run_async(
            resolve_and_authorize(
                action=action,
                resolver=chat_handler.agent.user_resolver,
                authorizer=authorizer,
                context=request_context,
                security_mode=mode,
            )
        )
        attach_resolved_user(request_context, user)
        run_async(enforce_rate_limit(rate_limiter, user, request_context))
        if guard_request is not None:
            _run_request_guard(guard_request, request_context)
        return user

    def _build_tool_context(
        user: User,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> ToolContext:
        return ToolContext(
            user=user,
            conversation_id=conversation_id or f"conv_{uuid.uuid4().hex[:8]}",
            request_id=request_id or str(uuid.uuid4()),
            agent_memory=chat_handler.agent.agent_memory,
            metadata={"schema_sync": True},
        )

    def _load_schema_metadata(context: ToolContext) -> Dict[str, Any]:
        service = config.get("schema_sync_service")
        if service is None:
            return {}
        latest = run_async(get_latest_snapshot_compat(service, context))
        if latest is None:
            return {}
        lineage: Dict[str, Any] = {
            "schema_hash": latest.schema_hash,
            "schema_snapshot_id": latest.snapshot_id,
        }
        schema_version = getattr(latest, "schema_version", None)
        if isinstance(schema_version, int):
            lineage["schema_version"] = schema_version
            lineage["schema_drift_detected"] = (
                getattr(latest, "previous_snapshot_id", None) is not None
            )
        return {TRUSTED_SCHEMA_LINEAGE_METADATA_KEY: lineage}

    def _feedback_service() -> Any:
        service = config.get("feedback_service")
        if service is None:
            raise ServiceNotConfiguredError()
        return service

    def _verify_feedback_conversation(
        conversation_id: str,
        request_id: str,
        user: User,
    ) -> None:
        try:
            conversation = run_async(
                chat_handler.agent.conversation_store.get_conversation(
                    conversation_id,
                    user,
                )
            )
        except ConversationAccessDeniedError as exc:
            raise RouteAccessDeniedError() from exc
        if conversation is None or not any(
            message.role == "user"
            and message.metadata.get(REQUEST_ID_METADATA_KEY) == request_id
            for message in conversation.messages
        ):
            raise RouteAccessDeniedError()

    def _raise_feedback_error(operation: str, error: Exception) -> None:
        if isinstance(error, (SqlPolicyViolation, ValueError)):
            raise InvalidRequestError() from error
        if isinstance(error, PermissionError):
            raise RouteAccessDeniedError() from error
        if isinstance(error, FeedbackStateError):
            raise RequestConflictError() from error
        raise _internal_error(operation) from error

    def _request_context(
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RequestContext:
        return RequestContext(
            cookies=dict(request.cookies),
            headers=dict(request.headers),
            remote_addr=request.remote_addr,
            query_params=dict(request.args),
            metadata=dict(metadata or {}),
        )

    def _json_object() -> Dict[str, Any]:
        try:
            data = request.get_json()
        except Exception as exc:
            raise InvalidRequestError() from exc
        if not isinstance(data, dict):
            raise InvalidRequestError()
        return data

    def _parse_chat_request(data: Dict[str, Any]) -> ChatRequest:
        try:
            return ChatRequest(**data)
        except Exception as exc:
            raise InvalidRequestError() from exc

    def _prepare_chat_request(*, v3: bool = False) -> ChatRequest:
        data = _json_object()
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise InvalidRequestError()
        request_context = _request_context(metadata)
        request_data = dict(data)
        request_data["request_context"] = request_context
        chat_request = _parse_chat_request(request_data)
        if v3:
            try:
                prepare_v3_request(chat_request)
            except ValueError as exc:
                raise InvalidRequestError() from exc
        user = _authorize(CHAT_EXECUTE, request_context, chat_request)
        if chat_request.conversation_id is not None:
            try:
                run_async(
                    chat_handler.agent.conversation_store.claim_conversation(
                        chat_request.conversation_id,
                        user,
                    )
                )
            except ConversationAccessDeniedError as exc:
                raise ConversationRouteAccessDeniedError() from exc
        tool_context = _build_tool_context(
            user,
            chat_request.conversation_id,
            chat_request.request_id,
        )
        schema_metadata = _load_schema_metadata(tool_context)
        if schema_metadata:
            chat_request.metadata = {**chat_request.metadata, **schema_metadata}
            request_context.metadata.update(schema_metadata)
        return chat_request

    if ui_enabled:
        index_html = get_index_html(
            dev_mode=bool(config.get("dev_mode", False)),
            static_path=config.get("static_url_path", "/static"),
            cdn_url=config.get("cdn_url"),
            component_script_path=config.get("component_script_path"),
            api_base_url=config.get("api_base_url", ""),
            api_v2_prefix=v2_prefix,
        )

        @app.route("/")
        def index() -> Response:
            """Serve the configured bundled chat interface."""

            request_context = _request_context()
            _authorize(UI_READ, request_context)
            return Response(
                index_html,
                mimetype="text/html",
                headers=bundled_ui_security_headers(),
            )

    @app.route(f"{v2_prefix}/chat_sse", methods=["POST"])
    def chat_sse() -> Response:
        """V2 Server-Sent Events chat endpoint."""

        chat_request = _prepare_chat_request()

        def generate() -> Generator[str, None, None]:
            async def async_generate() -> AsyncGenerator[str, None]:
                async for chunk in chat_handler.handle_stream(chat_request):
                    yield f"data: {chunk.model_dump_json()}\n\n"

            try:
                yield from iter_async(async_generate())
                yield "data: [DONE]\n\n"
            except Exception:
                error = _internal_error("flask.v2.chat_sse")
                error_data = {
                    "type": "error",
                    "data": {"message": error.public_message},
                    "conversation_id": chat_request.conversation_id or "",
                    "request_id": chat_request.request_id or "",
                }
                yield f"data: {json.dumps(error_data)}\n\n"

        return _sse_response(generate())

    @app.route(f"{v3_prefix}/chat/events", methods=["POST"])
    def chat_events_v3() -> Response:
        """Versioned V3 SSE endpoint with typed events."""

        chat_request = _prepare_chat_request(v3=True)

        def generate() -> Generator[str, None, None]:
            async def async_generate() -> AsyncGenerator[str, None]:
                conversation_id = str(chat_request.conversation_id)
                request_id = str(chat_request.request_id)
                async for event in iter_v3_events(
                    chat_handler.handle_stream(chat_request),
                    conversation_id=conversation_id,
                    request_id=request_id,
                    internal_error_factory=lambda: _internal_error(
                        "flask.v3.chat_events"
                    ),
                ):
                    yield format_sse_event(event)

            yield from iter_async(async_generate())

        return _sse_response(generate())

    @app.route(f"{v3_prefix}/chat/poll", methods=["POST"])
    def chat_poll_v3() -> Response:
        """Versioned V3 polling endpoint returning typed events."""

        chat_request = _prepare_chat_request(v3=True)
        response = run_async(
            collect_v3_poll(
                chat_handler.handle_stream(chat_request),
                conversation_id=str(chat_request.conversation_id),
                request_id=str(chat_request.request_id),
                internal_error_factory=lambda: _internal_error("flask.v3.chat_poll"),
            )
        )
        return jsonify(response.model_dump(mode="json"))

    @app.route(f"{v3_prefix}/schema/sync", methods=["POST"])
    def schema_sync() -> Response:
        """Trigger authorized on-demand schema synchronization."""

        request_context = _request_context()
        dummy_request = ChatRequest(message="", request_context=request_context)
        user = _authorize(SCHEMA_SYNC, request_context, dummy_request)
        service = config.get("schema_sync_service")
        if service is None:
            raise ServiceNotConfiguredError()
        tool_context = _build_tool_context(user)
        try:
            result = run_async(service.sync(tool_context))
            return jsonify(result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            raise _internal_error("flask.schema_sync") from exc

    @app.route(f"{v3_prefix}/schema/status", methods=["GET"])
    def schema_status() -> Response:
        """Return authorized schema snapshot metadata."""

        request_context = _request_context()
        user = _authorize(SCHEMA_READ, request_context)
        service = config.get("schema_sync_service")
        if service is None:
            raise ServiceNotConfiguredError()
        tool_context = _build_tool_context(user)
        try:
            latest = run_async(service.get_latest_snapshot(tool_context))
            if latest is None:
                return jsonify({"status": "empty", "snapshot": None})
            return jsonify({"status": "ok", "snapshot": latest.model_dump(mode="json")})
        except PublicServerError:
            raise
        except Exception as exc:
            raise _internal_error("flask.schema_status") from exc

    @app.route(f"{v3_prefix}/feedback", methods=["POST"])
    def feedback() -> Response:
        """Capture feedback after authentication and authorization."""

        data = _json_object()
        try:
            feedback_request = FeedbackRequest(**data)
        except Exception as exc:
            raise InvalidRequestError() from exc

        request_context = _request_context()
        dummy_request = ChatRequest(message="", request_context=request_context)
        user = _authorize(FEEDBACK_CREATE, request_context, dummy_request)
        _verify_feedback_conversation(
            feedback_request.conversation_id,
            feedback_request.request_id,
            user,
        )
        feedback_service = _feedback_service()
        tool_context = _build_tool_context(
            user,
            conversation_id=feedback_request.conversation_id,
            request_id=feedback_request.request_id,
        )
        try:
            result = run_async(
                feedback_service.process_feedback(feedback_request, tool_context)
            )
            return jsonify(result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("flask.feedback", exc)
            raise AssertionError("unreachable")

    @app.route(f"{v3_prefix}/feedback/review", methods=["GET"])
    def feedback_review_queue() -> Response:
        """List tenant-scoped feedback for authenticated admins."""

        status = request.args.get("status", "pending")
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError as exc:
            raise InvalidRequestError() from exc
        if status not in {"pending", "approved", "rejected"} or not 1 <= limit <= 1000:
            raise InvalidRequestError()
        request_context = _request_context()
        user = _authorize(FEEDBACK_REVIEW, request_context)
        tool_context = _build_tool_context(user)
        try:
            result = run_async(
                _feedback_service().list_review_queue(
                    tool_context,
                    status=status,
                    limit=limit,
                )
            )
            return jsonify(result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("flask.feedback_review_list", exc)
            raise AssertionError("unreachable")

    @app.route(f"{v3_prefix}/feedback/<feedback_id>/review", methods=["POST"])
    def review_feedback(feedback_id: str) -> Response:
        """Atomically approve or reject a pending tenant feedback record."""

        if not 1 <= len(feedback_id) <= 160:
            raise InvalidRequestError()
        try:
            review_request = FeedbackReviewRequest(**_json_object())
        except Exception as exc:
            raise InvalidRequestError() from exc
        request_context = _request_context()
        user = _authorize(FEEDBACK_REVIEW, request_context)
        tool_context = _build_tool_context(user)
        try:
            result = run_async(
                _feedback_service().review_feedback(
                    feedback_id,
                    review_request,
                    tool_context,
                )
            )
            return jsonify(result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("flask.feedback_review", exc)
            raise AssertionError("unreachable")

    @app.route(f"{v3_prefix}/feedback/export", methods=["GET"])
    def export_feedback() -> Response:
        """Export only approved records for this admin's tenant."""

        request_context = _request_context()
        user = _authorize(FEEDBACK_EXPORT, request_context)
        tool_context = _build_tool_context(user)
        try:
            result = run_async(_feedback_service().approved_export(tool_context))
            return jsonify(result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("flask.feedback_export", exc)
            raise AssertionError("unreachable")

    @app.route(f"{v2_prefix}/chat_websocket")
    def chat_websocket() -> tuple[Response, int]:
        """Explicitly report that Flask WebSocket parity is unsupported."""

        request_context = _request_context()
        _authorize(CHAT_EXECUTE, request_context)
        return jsonify(
            {
                "error": "WebSocket endpoint not implemented in basic Flask example",
                "suggestion": "Use Flask-SocketIO for WebSocket support",
            }
        ), 501

    @app.route(f"{v2_prefix}/chat_poll", methods=["POST"])
    def chat_poll() -> Response:
        """V2 polling endpoint with unchanged authorized response payload."""

        chat_request = _prepare_chat_request()
        try:
            result = run_async(chat_handler.handle_poll(chat_request))
            return jsonify(result.model_dump())
        except PublicServerError:
            raise
        except Exception as exc:
            raise _internal_error("flask.v2.chat_poll") from exc


def _sse_response(content: Generator[str, None, None]) -> Response:
    return Response(
        content,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _internal_error(operation: str) -> InternalServerError:
    error = InternalServerError()
    logger.error(
        "Server operation failed operation=%s correlation_id=%s",
        operation,
        error.correlation_id,
    )
    return error
