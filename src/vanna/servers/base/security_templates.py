"""Reference auth and rate-limit templates for server hardening."""

from __future__ import annotations

from typing import Any, Callable

from .errors import AuthenticationRequiredError, public_error_payload
from .rate_limit import FixedWindowRateLimiter, make_fixed_window_rate_limiter


def make_fastapi_bearer_auth_middleware(
    token_validator: Callable[[str], bool],
) -> Callable[[Any], None]:
    """Create a FastAPI middleware hook for bearer token validation."""

    def middleware_hook(app: Any) -> None:
        @app.middleware("http")  # type: ignore[untyped-decorator]
        async def auth_middleware(request: Any, call_next: Any) -> Any:
            # Allow health checks without auth.
            if request.url.path.endswith("/health"):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                from fastapi.responses import JSONResponse

                error = AuthenticationRequiredError()
                return JSONResponse(
                    status_code=error.status_code,
                    content=public_error_payload(error),
                )

            token = auth_header.split(" ", 1)[1]
            if not token_validator(token):
                from fastapi.responses import JSONResponse

                error = AuthenticationRequiredError()
                return JSONResponse(
                    status_code=error.status_code,
                    content=public_error_payload(error),
                )

            return await call_next(request)

    return middleware_hook


def make_flask_bearer_auth_middleware(
    token_validator: Callable[[str], bool],
) -> Callable[[Any], None]:
    """Create a Flask before_request auth hook."""

    def middleware_hook(app: Any) -> None:
        from flask import jsonify, request

        @app.before_request  # type: ignore[untyped-decorator]
        def auth_check() -> Any:
            if request.path.endswith("/health"):
                return None

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                error = AuthenticationRequiredError()
                return jsonify(public_error_payload(error)), error.status_code

            token = auth_header.split(" ", 1)[1]
            if not token_validator(token):
                error = AuthenticationRequiredError()
                return jsonify(public_error_payload(error)), error.status_code

            return None

    return middleware_hook


__all__ = [
    "FixedWindowRateLimiter",
    "make_fastapi_bearer_auth_middleware",
    "make_fixed_window_rate_limiter",
    "make_flask_bearer_auth_middleware",
]
