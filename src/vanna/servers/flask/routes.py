"""
Flask route implementations for Vanna Agents.
"""

import asyncio
import json
import traceback
import uuid
import inspect
from typing import Any, AsyncGenerator, Dict, Generator, Optional, Union, Callable

from flask import Flask, Response, jsonify, request

from ..base import ChatHandler, ChatRequest
from ..base.events_v3 import ChatEvent
from ..base.templates import get_index_html
from ...core.user.request_context import RequestContext
from ...core.tool import ToolContext
from ...services.feedback import FeedbackRequest


def register_chat_routes(
    app: Flask, chat_handler: ChatHandler, config: Optional[Dict[str, Any]] = None
) -> None:
    """Register chat routes on Flask app.

    Args:
        app: Flask application
        chat_handler: Chat handler instance
        config: Server configuration
    """
    config = config or {}
    v2_prefix = config.get("api_v2_prefix", "/api/vanna/v2")
    v3_prefix = config.get("api_v3_prefix", "/api/vanna/v3")
    enable_default_ui_route = config.get("enable_default_ui_route", True)
    request_guard: Optional[Callable[[ChatRequest, RequestContext], Any]] = config.get(
        "request_guard"
    )

    def _run_request_guard(chat_request: ChatRequest, request_context: RequestContext):
        if request_guard is None:
            return
        result = request_guard(chat_request, request_context)
        if inspect.isawaitable(result):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(result)
            finally:
                loop.close()

    def _build_tool_context(request_context: RequestContext) -> ToolContext:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            user = loop.run_until_complete(
                chat_handler.agent.user_resolver.resolve_user(request_context)
            )
        finally:
            loop.close()
        return ToolContext(
            user=user,
            conversation_id=f"conv_{uuid.uuid4().hex[:8]}",
            request_id=str(uuid.uuid4()),
            agent_memory=chat_handler.agent.agent_memory,
            metadata={"schema_sync": True},
        )

    def _load_schema_metadata_sync() -> Dict[str, Any]:
        service = config.get("schema_sync_service")
        if service is None:
            return {}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            latest = loop.run_until_complete(service.get_latest_snapshot())
        finally:
            loop.close()

        if latest is None:
            return {}
        return {
            "schema_hash": latest.schema_hash,
            "schema_snapshot_id": latest.snapshot_id,
        }

    if enable_default_ui_route:

        @app.route("/")
        def index() -> str:
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

    @app.route(f"{v2_prefix}/chat_sse", methods=["POST"])
    def chat_sse() -> Union[Response, tuple[Response, int]]:
        """Server-Sent Events endpoint for streaming chat."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON body required"}), 400
            data["metadata"] = {
                **data.get("metadata", {}),
                **_load_schema_metadata_sync(),
            }

            # Extract request context for user resolution
            data["request_context"] = RequestContext(
                cookies=dict(request.cookies),
                headers=dict(request.headers),
                remote_addr=request.remote_addr,
                query_params=dict(request.args),
                metadata=data.get("metadata", {}),
            )

            chat_request = ChatRequest(**data)
            _run_request_guard(chat_request, chat_request.request_context)
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        def generate() -> Generator[str, None, None]:
            """Generate SSE stream."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:

                async def async_generate() -> AsyncGenerator[str, None]:
                    async for chunk in chat_handler.handle_stream(chat_request):
                        chunk_json = chunk.model_dump_json()
                        yield f"data: {chunk_json}\n\n"

                gen = async_generate()
                try:
                    while True:
                        chunk = loop.run_until_complete(gen.__anext__())
                        yield chunk
                except StopAsyncIteration:
                    yield "data: [DONE]\n\n"
            finally:
                loop.close()

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @app.route(f"{v3_prefix}/chat/events", methods=["POST"])
    def chat_events_v3() -> Union[Response, tuple[Response, int]]:
        """Versioned v3 SSE endpoint with typed events."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON body required"}), 400
            data["metadata"] = {
                **data.get("metadata", {}),
                **_load_schema_metadata_sync(),
            }

            data["request_context"] = RequestContext(
                cookies=dict(request.cookies),
                headers=dict(request.headers),
                remote_addr=request.remote_addr,
                query_params=dict(request.args),
                metadata=data.get("metadata", {}),
            )
            chat_request = ChatRequest(**data)
            _run_request_guard(chat_request, chat_request.request_context)
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        def generate() -> Generator[str, None, None]:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            last_conversation_id = chat_request.conversation_id or ""
            last_request_id = chat_request.request_id or ""

            try:

                async def async_generate() -> AsyncGenerator[str, None]:
                    nonlocal last_conversation_id, last_request_id
                    async for chunk in chat_handler.handle_stream(chat_request):
                        last_conversation_id = chunk.conversation_id
                        last_request_id = chunk.request_id
                        event = ChatEvent.from_chunk(chunk)
                        event_json = event.model_dump_json()
                        yield f"event: {event.event_type}\n"
                        yield f"data: {event_json}\n\n"

                gen = async_generate()
                try:
                    while True:
                        chunk = loop.run_until_complete(gen.__anext__())
                        yield chunk
                except StopAsyncIteration:
                    done = ChatEvent.done(last_conversation_id, last_request_id)
                    yield "event: done\n"
                    yield f"data: {done.model_dump_json()}\n\n"
            finally:
                loop.close()

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route(f"{v3_prefix}/chat/poll", methods=["POST"])
    def chat_poll_v3() -> Union[Response, tuple[Response, int]]:
        """Versioned v3 polling endpoint returning typed events."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON body required"}), 400
            data["metadata"] = {
                **data.get("metadata", {}),
                **_load_schema_metadata_sync(),
            }

            data["request_context"] = RequestContext(
                cookies=dict(request.cookies),
                headers=dict(request.headers),
                remote_addr=request.remote_addr,
                query_params=dict(request.args),
                metadata=data.get("metadata", {}),
            )
            chat_request = ChatRequest(**data)
            _run_request_guard(chat_request, chat_request.request_context)
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            events = []

            async def collect():
                async for chunk in chat_handler.handle_stream(chat_request):
                    events.append(ChatEvent.from_chunk(chunk).model_dump())

            loop.run_until_complete(collect())
            if events:
                events.append(
                    ChatEvent.done(
                        events[0]["conversation_id"], events[0]["request_id"]
                    ).model_dump()
                )
            return jsonify({"event_version": "v3", "events": events})
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Chat failed: {str(e)}"}), 500
        finally:
            loop.close()

    @app.route(f"{v3_prefix}/schema/sync", methods=["POST"])
    def schema_sync() -> Union[Response, tuple[Response, int]]:
        """Trigger on-demand schema sync and drift detection."""
        service = config.get("schema_sync_service")
        if service is None:
            return jsonify({"error": "Schema sync service is not configured."}), 501

        request_context = RequestContext(
            cookies=dict(request.cookies),
            headers=dict(request.headers),
            remote_addr=request.remote_addr,
            query_params=dict(request.args),
            metadata={},
        )
        dummy_request = ChatRequest(message="", request_context=request_context)
        _run_request_guard(dummy_request, request_context)
        tool_context = _build_tool_context(request_context)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(service.sync(tool_context))
            return jsonify(result.model_dump(mode="json"))
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Schema sync failed: {str(e)}"}), 500
        finally:
            loop.close()

    @app.route(f"{v3_prefix}/schema/status", methods=["GET"])
    def schema_status() -> Union[Response, tuple[Response, int]]:
        """Return latest known schema snapshot metadata."""
        service = config.get("schema_sync_service")
        if service is None:
            return jsonify({"error": "Schema sync service is not configured."}), 501

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            latest = loop.run_until_complete(service.get_latest_snapshot())
            if latest is None:
                return jsonify({"status": "empty", "snapshot": None})
            return jsonify({"status": "ok", "snapshot": latest.model_dump(mode="json")})
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Schema status failed: {str(e)}"}), 500
        finally:
            loop.close()

    @app.route(f"{v3_prefix}/feedback", methods=["POST"])
    def feedback() -> Union[Response, tuple[Response, int]]:
        """Capture feedback and apply immediate memory patches."""
        feedback_service = config.get("feedback_service")
        if feedback_service is None:
            return jsonify({"error": "Feedback service is not configured."}), 501

        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON body required"}), 400
            feedback_request = FeedbackRequest(**data)
        except Exception as e:
            return jsonify({"error": f"Invalid feedback request: {str(e)}"}), 400

        request_context = RequestContext(
            cookies=dict(request.cookies),
            headers=dict(request.headers),
            remote_addr=request.remote_addr,
            query_params=dict(request.args),
            metadata={},
        )
        dummy_request = ChatRequest(message="", request_context=request_context)
        _run_request_guard(dummy_request, request_context)

        tool_context = _build_tool_context(request_context)
        if feedback_request.conversation_id:
            tool_context.conversation_id = feedback_request.conversation_id
        if feedback_request.request_id:
            tool_context.request_id = feedback_request.request_id

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                feedback_service.process_feedback(feedback_request, tool_context)
            )
            return jsonify(result.model_dump(mode="json"))
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Feedback processing failed: {str(e)}"}), 500
        finally:
            loop.close()

    @app.route(f"{v2_prefix}/chat_websocket")
    def chat_websocket() -> tuple[Response, int]:
        """WebSocket endpoint placeholder."""
        return jsonify(
            {
                "error": "WebSocket endpoint not implemented in basic Flask example",
                "suggestion": "Use Flask-SocketIO for WebSocket support",
            }
        ), 501

    @app.route(f"{v2_prefix}/chat_poll", methods=["POST"])
    def chat_poll() -> Union[Response, tuple[Response, int]]:
        """Polling endpoint for chat."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON body required"}), 400
            data["metadata"] = {
                **data.get("metadata", {}),
                **_load_schema_metadata_sync(),
            }

            # Extract request context for user resolution
            data["request_context"] = RequestContext(
                cookies=dict(request.cookies),
                headers=dict(request.headers),
                remote_addr=request.remote_addr,
                query_params=dict(request.args),
                metadata=data.get("metadata", {}),
            )

            chat_request = ChatRequest(**data)
            _run_request_guard(chat_request, chat_request.request_context)
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        # Run async handler in new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(chat_handler.handle_poll(chat_request))
            return jsonify(result.model_dump())
        except Exception as e:
            traceback.print_stack()
            traceback.print_exc()
            return jsonify({"error": f"Chat failed: {str(e)}"}), 500
        finally:
            loop.close()
