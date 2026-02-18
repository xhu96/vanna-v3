"""Reference auth and rate-limit templates for server hardening."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, Optional


def make_fastapi_bearer_auth_middleware(
    token_validator: Callable[[str], bool]
) -> Callable[[Any], None]:
    """Create a FastAPI middleware hook for bearer token validation."""

    def middleware_hook(app: Any) -> None:
        @app.middleware("http")
        async def auth_middleware(request: Any, call_next: Any) -> Any:
            # Allow health checks without auth.
            if request.url.path.endswith("/health"):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=401, content={"detail": "Missing token"})

            token = auth_header.split(" ", 1)[1]
            if not token_validator(token):
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=401, content={"detail": "Invalid token"})

            return await call_next(request)

    return middleware_hook


def make_flask_bearer_auth_middleware(
    token_validator: Callable[[str], bool]
) -> Callable[[Any], None]:
    """Create a Flask before_request auth hook."""

    def middleware_hook(app: Any) -> None:
        from flask import jsonify, request

        @app.before_request
        def auth_check():
            if request.path.endswith("/health"):
                return None

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing token"}), 401

            token = auth_header.split(" ", 1)[1]
            if not token_validator(token):
                return jsonify({"error": "Invalid token"}), 401

            return None

    return middleware_hook


def make_fixed_window_rate_limiter(
    requests_per_minute: int = 120,
) -> Callable[[Any, Any], None]:
    """Create a request_guard-compatible rate limit hook."""

    buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def guard(chat_request: Any, request_context: Any) -> None:
        identity = (
            request_context.headers.get("x-forwarded-for")
            or request_context.remote_addr
            or "unknown"
        )
        now = time.time()
        window_start = now - 60.0
        queue = buckets[identity]

        while queue and queue[0] < window_start:
            queue.popleft()

        if len(queue) >= requests_per_minute:
            raise PermissionError("Rate limit exceeded for this client.")

        queue.append(now)

    return guard

