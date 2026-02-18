"""
FastAPI route implementations for Vanna Agents.
"""

import json
import traceback
import uuid
import inspect
from typing import Any, AsyncGenerator, Dict, Optional, Callable, Awaitable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse

from ..base import ChatHandler, ChatRequest, ChatResponse
from ..base.events_v3 import ChatEvent
from ..base.templates import get_index_html
from ...core.user.request_context import RequestContext
from ...core.tool import ToolContext
from ...services.feedback import FeedbackRequest


def register_chat_routes(
    app: FastAPI, chat_handler: ChatHandler, config: Optional[Dict[str, Any]] = None
) -> None:
    """Register chat routes on FastAPI app.

    Args:
        app: FastAPI application
        chat_handler: Chat handler instance
        config: Server configuration
    """
    config = config or {}
    v2_prefix = config.get("api_v2_prefix", "/api/vanna/v2")
    v3_prefix = config.get("api_v3_prefix", "/api/vanna/v3")
    enable_default_ui_route = config.get("enable_default_ui_route", True)
    request_guard: Optional[
        Callable[[ChatRequest, RequestContext], Optional[Awaitable[None]]]
    ] = config.get("request_guard")

    async def _run_request_guard(
        chat_request: ChatRequest, request_context: RequestContext
    ) -> None:
        if request_guard is None:
            return
        result = request_guard(chat_request, request_context)
        if inspect.isawaitable(result):
            await result

    async def _build_tool_context(
        request_context: RequestContext,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> ToolContext:
        user = await chat_handler.agent.user_resolver.resolve_user(request_context)
        return ToolContext(
            user=user,
            conversation_id=conversation_id or f"conv_{uuid.uuid4().hex[:8]}",
            request_id=request_id or str(uuid.uuid4()),
            agent_memory=chat_handler.agent.agent_memory,
            metadata={"schema_sync": True},
        )

    async def _load_schema_metadata() -> Dict[str, Any]:
        service = config.get("schema_sync_service")
        if service is None:
            return {}
        latest = await service.get_latest_snapshot()
        if latest is None:
            return {}
        return {
            "schema_hash": latest.schema_hash,
            "schema_snapshot_id": latest.snapshot_id,
        }

    if enable_default_ui_route:

        @app.get("/", response_class=HTMLResponse)
        async def index() -> str:
            """Serve the main chat interface."""
            dev_mode = config.get("dev_mode", False)
            cdn_url = config.get("cdn_url", "https://img.vanna.ai/vanna-components.js")
            api_base_url = config.get("api_base_url", "")

        return get_index_html(
            dev_mode=dev_mode,
            cdn_url=cdn_url,
            api_base_url=api_base_url,
            api_v2_prefix=v2_prefix,
        )

    @app.post(f"{v2_prefix}/chat_sse")
    async def chat_sse(
        chat_request: ChatRequest, http_request: Request
    ) -> StreamingResponse:
        """Server-Sent Events endpoint for streaming chat."""
        merged_metadata = {**chat_request.metadata, **(await _load_schema_metadata())}
        chat_request.metadata = merged_metadata
        # Extract request context for user resolution
        chat_request.request_context = RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata=merged_metadata,
        )
        await _run_request_guard(chat_request, chat_request.request_context)

        async def generate() -> AsyncGenerator[str, None]:
            """Generate SSE stream."""
            try:
                async for chunk in chat_handler.handle_stream(chat_request):
                    chunk_json = chunk.model_dump_json()
                    yield f"data: {chunk_json}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                traceback.print_stack()
                traceback.print_exc()
                error_data = {
                    "type": "error",
                    "data": {"message": str(e)},
                    "conversation_id": chat_request.conversation_id or "",
                    "request_id": chat_request.request_id or "",
                }
                yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @app.post(f"{v3_prefix}/chat/events")
    async def chat_events_v3(
        chat_request: ChatRequest, http_request: Request
    ) -> StreamingResponse:
        """Versioned v3 SSE endpoint with typed events."""
        merged_metadata = {**chat_request.metadata, **(await _load_schema_metadata())}
        chat_request.metadata = merged_metadata
        chat_request.request_context = RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata=merged_metadata,
        )
        await _run_request_guard(chat_request, chat_request.request_context)

        async def generate() -> AsyncGenerator[str, None]:
            last_conversation_id = chat_request.conversation_id or ""
            last_request_id = chat_request.request_id or ""
            try:
                async for chunk in chat_handler.handle_stream(chat_request):
                    last_conversation_id = chunk.conversation_id
                    last_request_id = chunk.request_id
                    event = ChatEvent.from_chunk(chunk)
                    event_json = event.model_dump_json()
                    yield f"event: {event.event_type}\n"
                    yield f"data: {event_json}\n\n"

                done_event = ChatEvent.done(last_conversation_id, last_request_id)
                yield "event: done\n"
                yield f"data: {done_event.model_dump_json()}\n\n"
            except Exception as e:
                error_event = ChatEvent(
                    event_type="error",
                    conversation_id=last_conversation_id,
                    request_id=last_request_id,
                    payload={"message": str(e)},
                )
                yield "event: error\n"
                yield f"data: {error_event.model_dump_json()}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post(f"{v3_prefix}/chat/poll")
    async def chat_poll_v3(
        chat_request: ChatRequest, http_request: Request
    ) -> Dict[str, Any]:
        """Versioned v3 polling endpoint returning typed events."""
        merged_metadata = {**chat_request.metadata, **(await _load_schema_metadata())}
        chat_request.metadata = merged_metadata
        chat_request.request_context = RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata=merged_metadata,
        )
        await _run_request_guard(chat_request, chat_request.request_context)

        events = []
        async for chunk in chat_handler.handle_stream(chat_request):
            events.append(ChatEvent.from_chunk(chunk).model_dump())

        if events:
            conversation_id = events[0]["conversation_id"]
            request_id = events[0]["request_id"]
            events.append(ChatEvent.done(conversation_id, request_id).model_dump())

        return {"event_version": "v3", "events": events}

    @app.post(f"{v3_prefix}/schema/sync")
    async def schema_sync(http_request: Request) -> Dict[str, Any]:
        """Trigger on-demand schema sync and drift detection."""
        service = config.get("schema_sync_service")
        if service is None:
            raise HTTPException(
                status_code=501, detail="Schema sync service is not configured."
            )

        request_context = RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata={},
        )
        dummy_request = ChatRequest(message="", request_context=request_context)
        await _run_request_guard(dummy_request, request_context)
        tool_context = await _build_tool_context(request_context)
        result = await service.sync(tool_context)
        return result.model_dump(mode="json")

    @app.get(f"{v3_prefix}/schema/status")
    async def schema_status() -> Dict[str, Any]:
        """Return latest known schema snapshot metadata."""
        service = config.get("schema_sync_service")
        if service is None:
            raise HTTPException(
                status_code=501, detail="Schema sync service is not configured."
            )
        latest = await service.get_latest_snapshot()
        if latest is None:
            return {"status": "empty", "snapshot": None}
        return {"status": "ok", "snapshot": latest.model_dump(mode="json")}

    @app.post(f"{v3_prefix}/feedback")
    async def feedback(
        feedback_request: FeedbackRequest, http_request: Request
    ) -> Dict[str, Any]:
        """Capture feedback and apply immediate memory patches."""
        feedback_service = config.get("feedback_service")
        if feedback_service is None:
            raise HTTPException(
                status_code=501, detail="Feedback service is not configured."
            )

        request_context = RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata={},
        )
        dummy_request = ChatRequest(message="", request_context=request_context)
        await _run_request_guard(dummy_request, request_context)

        tool_context = await _build_tool_context(
            request_context=request_context,
            conversation_id=feedback_request.conversation_id,
            request_id=feedback_request.request_id,
        )
        result = await feedback_service.process_feedback(feedback_request, tool_context)
        return result.model_dump(mode="json")

    @app.websocket(f"{v2_prefix}/chat_websocket")
    async def chat_websocket(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time chat."""
        await websocket.accept()

        try:
            while True:
                # Receive message
                try:
                    data = await websocket.receive_json()

                    # Extract request context for user resolution
                    metadata = data.get("metadata", {})
                    metadata = {**metadata, **(await _load_schema_metadata())}
                    data["request_context"] = RequestContext(
                        cookies=dict(websocket.cookies),
                        headers=dict(websocket.headers),
                        remote_addr=websocket.client.host if websocket.client else None,
                        query_params=dict(websocket.query_params),
                        metadata=metadata,
                    )

                    chat_request = ChatRequest(**data)
                    await _run_request_guard(chat_request, chat_request.request_context)
                except Exception as e:
                    traceback.print_stack()
                    traceback.print_exc()
                    await websocket.send_json(
                        {
                            "type": "error",
                            "data": {"message": f"Invalid request: {str(e)}"},
                        }
                    )
                    continue

                # Stream response
                try:
                    async for chunk in chat_handler.handle_stream(chat_request):
                        await websocket.send_json(chunk.model_dump())

                    # Send completion signal
                    await websocket.send_json(
                        {
                            "type": "completion",
                            "data": {"status": "done"},
                            "conversation_id": chunk.conversation_id
                            if "chunk" in locals()
                            else "",
                            "request_id": chunk.request_id
                            if "chunk" in locals()
                            else "",
                        }
                    )

                except Exception as e:
                    traceback.print_stack()
                    traceback.print_exc()
                    await websocket.send_json(
                        {
                            "type": "error",
                            "data": {"message": str(e)},
                            "conversation_id": chat_request.conversation_id or "",
                            "request_id": chat_request.request_id or "",
                        }
                    )

        except WebSocketDisconnect:
            pass
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {"message": f"WebSocket error: {str(e)}"},
                    }
                )
            except Exception:
                pass
            finally:
                await websocket.close()

    @app.post(f"{v2_prefix}/chat_poll")
    async def chat_poll(
        chat_request: ChatRequest, http_request: Request
    ) -> ChatResponse:
        """Polling endpoint for chat."""
        merged_metadata = {**chat_request.metadata, **(await _load_schema_metadata())}
        chat_request.metadata = merged_metadata
        # Extract request context for user resolution
        chat_request.request_context = RequestContext(
            cookies=dict(http_request.cookies),
            headers=dict(http_request.headers),
            remote_addr=http_request.client.host if http_request.client else None,
            query_params=dict(http_request.query_params),
            metadata=merged_metadata,
        )
        await _run_request_guard(chat_request, chat_request.request_context)

        try:
            result = await chat_handler.handle_poll(chat_request)
            return result
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")
