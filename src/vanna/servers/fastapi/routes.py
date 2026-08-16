"""FastAPI route implementations for Vanna Agents."""

import asyncio
import inspect
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Callable, Dict, Optional, cast

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse

from ...capabilities.schema_catalog import get_latest_snapshot_compat
from ...core.storage import ConversationAccessDeniedError, REQUEST_ID_METADATA_KEY
from ...core.tool import ToolContext
from ...core.user import (
    RequestContext,
    TRUSTED_SCHEMA_LINEAGE_METADATA_KEY,
    User,
    same_principal,
)
from ...security.sql_policy import SqlPolicyViolation
from ...services.feedback import FeedbackRequest, FeedbackReviewRequest
from ...services.feedback_store import FeedbackStateError
from ..base import ChatHandler, ChatRequest, ChatResponse
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
    AuthenticationRequiredError,
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

logger = logging.getLogger(__name__)


def register_chat_routes(
    app: FastAPI, chat_handler: ChatHandler, config: Optional[Dict[str, Any]] = None
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

    async def _run_request_guard(
        chat_request: ChatRequest, request_context: RequestContext
    ) -> None:
        if request_guard is None:
            return
        try:
            result = request_guard(chat_request, request_context)
            if inspect.isawaitable(result):
                result = await result
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

    async def _authorize(
        action: str,
        request_context: RequestContext,
        guard_request: Optional[ChatRequest] = None,
        *,
        apply_rate_limit: bool = True,
        expected_user: Optional[User] = None,
    ) -> User:
        user = await resolve_and_authorize(
            action=action,
            resolver=chat_handler.agent.user_resolver,
            authorizer=authorizer,
            context=request_context,
            security_mode=mode,
        )
        if expected_user is not None and not same_principal(user, expected_user):
            raise AuthenticationRequiredError()
        attach_resolved_user(request_context, user)
        if apply_rate_limit:
            await enforce_rate_limit(rate_limiter, user, request_context)
        if guard_request is not None:
            await _run_request_guard(guard_request, request_context)
        return user

    async def _build_tool_context(
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

    async def _load_schema_metadata(context: ToolContext) -> Dict[str, Any]:
        service = config.get("schema_sync_service")
        if service is None:
            return {}
        latest = await get_latest_snapshot_compat(service, context)
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

    async def _verify_feedback_conversation(
        conversation_id: str,
        request_id: str,
        user: User,
    ) -> None:
        try:
            conversation = await chat_handler.agent.conversation_store.get_conversation(
                conversation_id,
                user,
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

    def _http_context(
        http_request: Request, metadata: Optional[Dict[str, Any]] = None
    ) -> RequestContext:
        return RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata=dict(metadata or {}),
        )

    def _websocket_context(
        websocket: WebSocket, metadata: Optional[Dict[str, Any]] = None
    ) -> RequestContext:
        return RequestContext(
            cookies=dict(websocket.cookies),
            headers=dict(websocket.headers),
            remote_addr=websocket.client.host if websocket.client else None,
            query_params=dict(websocket.query_params),
            metadata=dict(metadata or {}),
        )

    async def _claim_conversation(
        conversation_id: Optional[str],
        user: User,
    ) -> None:
        if conversation_id is None:
            return
        try:
            await chat_handler.agent.conversation_store.claim_conversation(
                conversation_id,
                user,
            )
        except ConversationAccessDeniedError as exc:
            raise ConversationRouteAccessDeniedError() from exc

    async def _prepare_chat_request(
        chat_request: ChatRequest,
        http_request: Request,
        *,
        v3: bool = False,
    ) -> None:
        if v3:
            try:
                prepare_v3_request(chat_request)
            except ValueError as exc:
                raise InvalidRequestError() from exc
        request_context = _http_context(http_request, chat_request.metadata)
        chat_request.request_context = request_context
        user = await _authorize(CHAT_EXECUTE, request_context, chat_request)
        await _claim_conversation(chat_request.conversation_id, user)
        tool_context = await _build_tool_context(
            user,
            chat_request.conversation_id,
            chat_request.request_id,
        )
        schema_metadata = await _load_schema_metadata(tool_context)
        if schema_metadata:
            chat_request.metadata = {**chat_request.metadata, **schema_metadata}
            request_context.metadata.update(schema_metadata)

    if ui_enabled:
        index_html = get_index_html(
            dev_mode=bool(config.get("dev_mode", False)),
            static_path=config.get("static_url_path", "/static"),
            cdn_url=config.get("cdn_url"),
            component_script_path=config.get("component_script_path"),
            api_base_url=config.get("api_base_url", ""),
            api_v2_prefix=v2_prefix,
        )

        @app.get("/", response_class=HTMLResponse)
        async def index(http_request: Request) -> HTMLResponse:
            """Serve the configured bundled chat interface."""

            request_context = _http_context(http_request)
            await _authorize(UI_READ, request_context)
            return HTMLResponse(
                content=index_html,
                headers=bundled_ui_security_headers(),
            )

    @app.post(f"{v2_prefix}/chat_sse")
    async def chat_sse(
        chat_request: ChatRequest, http_request: Request
    ) -> StreamingResponse:
        """V2 Server-Sent Events chat endpoint."""

        await _prepare_chat_request(chat_request, http_request)

        async def generate() -> AsyncGenerator[str, None]:
            try:
                async for chunk in chat_handler.handle_stream(chat_request):
                    yield f"data: {chunk.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                raise
            except Exception:
                error = _internal_error("fastapi.v2.chat_sse")
                error_data = {
                    "type": "error",
                    "data": {"message": error.public_message},
                    "conversation_id": chat_request.conversation_id or "",
                    "request_id": chat_request.request_id or "",
                }
                yield f"data: {json.dumps(error_data)}\n\n"

        return _sse_response(generate())

    @app.post(f"{v3_prefix}/chat/events")
    async def chat_events_v3(
        chat_request: ChatRequest, http_request: Request
    ) -> StreamingResponse:
        """Versioned V3 SSE endpoint with typed events."""

        await _prepare_chat_request(chat_request, http_request, v3=True)

        async def generate() -> AsyncGenerator[str, None]:
            conversation_id = cast(str, chat_request.conversation_id)
            request_id = cast(str, chat_request.request_id)
            events = iter_v3_events(
                chat_handler.handle_stream(chat_request),
                conversation_id=conversation_id,
                request_id=request_id,
                internal_error_factory=lambda: _internal_error(
                    "fastapi.v3.chat_events"
                ),
            )
            async for event in events:
                yield format_sse_event(event)

        return _sse_response(generate())

    @app.post(f"{v3_prefix}/chat/poll")
    async def chat_poll_v3(
        chat_request: ChatRequest, http_request: Request
    ) -> Dict[str, Any]:
        """Versioned V3 polling endpoint returning typed events."""

        await _prepare_chat_request(chat_request, http_request, v3=True)
        conversation_id = cast(str, chat_request.conversation_id)
        request_id = cast(str, chat_request.request_id)
        response = await collect_v3_poll(
            chat_handler.handle_stream(chat_request),
            conversation_id=conversation_id,
            request_id=request_id,
            internal_error_factory=lambda: _internal_error("fastapi.v3.chat_poll"),
        )
        return response.model_dump(mode="json")

    @app.post(f"{v3_prefix}/schema/sync")
    async def schema_sync(http_request: Request) -> Dict[str, Any]:
        """Trigger authorized on-demand schema synchronization."""

        request_context = _http_context(http_request)
        dummy_request = ChatRequest(message="", request_context=request_context)
        user = await _authorize(SCHEMA_SYNC, request_context, dummy_request)
        service = config.get("schema_sync_service")
        if service is None:
            raise ServiceNotConfiguredError()
        tool_context = await _build_tool_context(user)
        try:
            result = await service.sync(tool_context)
            return cast(Dict[str, Any], result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            raise _internal_error("fastapi.schema_sync") from exc

    @app.get(f"{v3_prefix}/schema/status")
    async def schema_status(http_request: Request) -> Dict[str, Any]:
        """Return authorized schema snapshot metadata."""

        request_context = _http_context(http_request)
        user = await _authorize(SCHEMA_READ, request_context)
        service = config.get("schema_sync_service")
        if service is None:
            raise ServiceNotConfiguredError()
        tool_context = await _build_tool_context(user)
        try:
            latest = await service.get_latest_snapshot(tool_context)
            if latest is None:
                return {"status": "empty", "snapshot": None}
            return {"status": "ok", "snapshot": latest.model_dump(mode="json")}
        except PublicServerError:
            raise
        except Exception as exc:
            raise _internal_error("fastapi.schema_status") from exc

    @app.post(f"{v3_prefix}/feedback")
    async def feedback(
        feedback_request: FeedbackRequest, http_request: Request
    ) -> Dict[str, Any]:
        """Capture feedback after authentication and authorization."""

        request_context = _http_context(http_request)
        dummy_request = ChatRequest(message="", request_context=request_context)
        user = await _authorize(FEEDBACK_CREATE, request_context, dummy_request)
        await _verify_feedback_conversation(
            feedback_request.conversation_id,
            feedback_request.request_id,
            user,
        )
        feedback_service = _feedback_service()
        tool_context = await _build_tool_context(
            user,
            conversation_id=feedback_request.conversation_id,
            request_id=feedback_request.request_id,
        )
        try:
            result = await feedback_service.process_feedback(
                feedback_request, tool_context
            )
            return cast(Dict[str, Any], result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("fastapi.feedback", exc)
            raise AssertionError("unreachable")

    @app.get(f"{v3_prefix}/feedback/review")
    async def feedback_review_queue(
        http_request: Request,
        status: str = "pending",
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List tenant-scoped feedback for authenticated admins."""

        if status not in {"pending", "approved", "rejected"} or not 1 <= limit <= 1000:
            raise InvalidRequestError()
        request_context = _http_context(http_request)
        user = await _authorize(FEEDBACK_REVIEW, request_context)
        tool_context = await _build_tool_context(user)
        try:
            result = await _feedback_service().list_review_queue(
                tool_context,
                status=status,
                limit=limit,
            )
            return cast(Dict[str, Any], result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("fastapi.feedback_review_list", exc)
            raise AssertionError("unreachable")

    @app.post(f"{v3_prefix}/feedback/{{feedback_id}}/review")
    async def review_feedback(
        feedback_id: str,
        review_request: FeedbackReviewRequest,
        http_request: Request,
    ) -> Dict[str, Any]:
        """Atomically approve or reject a pending tenant feedback record."""

        if not 1 <= len(feedback_id) <= 160:
            raise InvalidRequestError()
        request_context = _http_context(http_request)
        user = await _authorize(FEEDBACK_REVIEW, request_context)
        tool_context = await _build_tool_context(user)
        try:
            result = await _feedback_service().review_feedback(
                feedback_id,
                review_request,
                tool_context,
            )
            return cast(Dict[str, Any], result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("fastapi.feedback_review", exc)
            raise AssertionError("unreachable")

    @app.get(f"{v3_prefix}/feedback/export")
    async def export_feedback(http_request: Request) -> Dict[str, Any]:
        """Export only approved records for this admin's tenant."""

        request_context = _http_context(http_request)
        user = await _authorize(FEEDBACK_EXPORT, request_context)
        tool_context = await _build_tool_context(user)
        try:
            result = await _feedback_service().approved_export(tool_context)
            return cast(Dict[str, Any], result.model_dump(mode="json"))
        except PublicServerError:
            raise
        except Exception as exc:
            _raise_feedback_error("fastapi.feedback_export", exc)
            raise AssertionError("unreachable")

    @app.websocket(f"{v2_prefix}/chat_websocket")
    async def chat_websocket(websocket: WebSocket) -> None:
        """V2 WebSocket with authentication before protocol acceptance."""

        handshake_context = _websocket_context(websocket)
        try:
            user = await _authorize(
                CHAT_EXECUTE, handshake_context, apply_rate_limit=False
            )
        except PublicServerError as public_error:
            await websocket.close(
                code=_websocket_close_code(public_error), reason=public_error.code
            )
            return
        except Exception:
            await websocket.close(code=1011, reason="internal_error")
            return

        await websocket.accept()
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    if not isinstance(data, dict):
                        raise ValueError("WebSocket request must be an object")
                    metadata = data.get("metadata", {})
                    if not isinstance(metadata, dict):
                        raise ValueError("WebSocket metadata must be an object")
                    request_context = _websocket_context(websocket, metadata)
                    request_data = dict(data)
                    request_data["request_context"] = request_context
                    chat_request = ChatRequest(**request_data)
                    message_user = await _authorize(
                        CHAT_EXECUTE,
                        request_context,
                        chat_request,
                        expected_user=user,
                    )
                    await _claim_conversation(
                        chat_request.conversation_id, message_user
                    )
                except WebSocketDisconnect:
                    raise
                except PublicServerError as public_error:
                    await websocket.send_json(_v2_websocket_error(public_error))
                    continue
                except Exception:
                    await websocket.send_json(
                        _v2_websocket_error(_internal_error("fastapi.websocket.parse"))
                    )
                    continue

                try:
                    tool_context = await _build_tool_context(
                        message_user,
                        chat_request.conversation_id,
                        chat_request.request_id,
                    )
                    schema_metadata = await _load_schema_metadata(tool_context)
                    if schema_metadata:
                        chat_request.metadata = {
                            **chat_request.metadata,
                            **schema_metadata,
                        }
                        request_context.metadata.update(schema_metadata)

                    last_conversation_id = ""
                    last_request_id = ""
                    async for chunk in chat_handler.handle_stream(chat_request):
                        last_conversation_id = chunk.conversation_id
                        last_request_id = chunk.request_id
                        await websocket.send_json(chunk.model_dump())
                    await websocket.send_json(
                        {
                            "type": "completion",
                            "data": {"status": "done"},
                            "conversation_id": last_conversation_id,
                            "request_id": last_request_id,
                        }
                    )
                except WebSocketDisconnect:
                    raise
                except Exception:
                    internal_error = _internal_error("fastapi.websocket.chat")
                    await websocket.send_json(
                        _v2_websocket_error(
                            internal_error,
                            conversation_id=chat_request.conversation_id or "",
                            request_id=chat_request.request_id or "",
                        )
                    )
        except WebSocketDisconnect:
            return
        except Exception:
            internal_error = _internal_error("fastapi.websocket.connection")
            try:
                await websocket.send_json(_v2_websocket_error(internal_error))
            except Exception:
                pass
            try:
                await websocket.close(code=1011, reason=internal_error.code)
            except Exception:
                pass

    @app.post(f"{v2_prefix}/chat_poll")
    async def chat_poll(
        chat_request: ChatRequest, http_request: Request
    ) -> ChatResponse:
        """V2 polling endpoint with unchanged authorized response payload."""

        await _prepare_chat_request(chat_request, http_request)
        try:
            return await chat_handler.handle_poll(chat_request)
        except PublicServerError:
            raise
        except Exception as exc:
            raise _internal_error("fastapi.v2.chat_poll") from exc


def _sse_response(content: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        content,
        media_type="text/event-stream",
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


def _websocket_close_code(error: PublicServerError) -> int:
    return {401: 4401, 403: 4403, 429: 4429}.get(error.status_code, 1011)


def _v2_websocket_error(
    error: PublicServerError,
    *,
    conversation_id: str = "",
    request_id: str = "",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "error",
        "data": {"message": error.public_message},
    }
    if conversation_id or request_id:
        payload["conversation_id"] = conversation_id
        payload["request_id"] = request_id
    return payload
