"""Reference auth and rate-limit templates for server hardening."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict

from vanna.exceptions import VannaPermissionError


def make_fastapi_bearer_auth_middleware(
    token_validator: Callable[[str], bool],
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

                return JSONResponse(
                    status_code=401, content={"detail": "Missing token"}
                )

            token = auth_header.split(" ", 1)[1]
            if not token_validator(token):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=401, content={"detail": "Invalid token"}
                )

            return await call_next(request)

    return middleware_hook


def make_flask_bearer_auth_middleware(
    token_validator: Callable[[str], bool],
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
    trust_proxy_headers: bool = False,
    max_tracked_clients: int = 10_000,
) -> Callable[[Any, Any], None]:
    """Create a request_guard-compatible rate limit hook.

    Args:
        requests_per_minute: Maximum requests allowed per client per minute.
        trust_proxy_headers: If True, use the leftmost IP from X-Forwarded-For
            as the client identity. Only enable this when running behind a trusted
            reverse proxy that sets the header; otherwise clients can spoof it to
            bypass rate limiting.
        max_tracked_clients: Maximum number of distinct clients to track. Oldest
            entries are evicted once this limit is reached to cap memory usage.
    """

    buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def guard(chat_request: Any, request_context: Any) -> None:
        if trust_proxy_headers:
            xff = request_context.headers.get("x-forwarded-for", "")
            # Use only the leftmost IP — the original client address.
            identity = xff.split(",")[0].strip() or request_context.remote_addr or "unknown"
        else:
            identity = request_context.remote_addr or "unknown"

        # Evict the oldest tracked client when the cap is reached.
        if len(buckets) >= max_tracked_clients and identity not in buckets:
            oldest_key = next(iter(buckets))
            del buckets[oldest_key]

        now = time.time()
        window_start = now - 60.0
        queue = buckets[identity]

        while queue and queue[0] < window_start:
            queue.popleft()

        if len(queue) >= requests_per_minute:
            raise VannaPermissionError("Rate limit exceeded for this client.")

        queue.append(now)

    return guard
