"""
Base server components for the Vanna Agents framework.

This module provides framework-agnostic components for handling chat
requests and responses.
"""

from .chat_handler import ChatHandler
from .models import ChatRequest, ChatStreamChunk, ChatResponse
from .events_v3 import ChatEvent, ChatPollResponse
from .authorization import (
    CHAT_EXECUTE,
    FEEDBACK_CREATE,
    FEEDBACK_EXPORT,
    FEEDBACK_REVIEW,
    HEALTH_READ,
    SCHEMA_READ,
    SCHEMA_SYNC,
    UI_READ,
    DefaultRouteAuthorizer,
    RequestBoundUserResolver,
    RouteAuthorizer,
)
from .errors import (
    AuthenticationRequiredError,
    InternalServerError,
    InvalidRequestError,
    PublicServerError,
    RateLimitExceededError,
    RequestConflictError,
    RouteAccessDeniedError,
    ServiceNotConfiguredError,
)
from .rate_limit import FixedWindowRateLimiter, RateLimiter
from .security_templates import (
    make_fastapi_bearer_auth_middleware,
    make_flask_bearer_auth_middleware,
    make_fixed_window_rate_limiter,
)
from .templates import INDEX_HTML

__all__ = [
    "ChatHandler",
    "ChatRequest",
    "ChatStreamChunk",
    "ChatResponse",
    "ChatEvent",
    "ChatPollResponse",
    "CHAT_EXECUTE",
    "FEEDBACK_CREATE",
    "FEEDBACK_EXPORT",
    "FEEDBACK_REVIEW",
    "HEALTH_READ",
    "SCHEMA_READ",
    "SCHEMA_SYNC",
    "UI_READ",
    "RouteAuthorizer",
    "DefaultRouteAuthorizer",
    "RequestBoundUserResolver",
    "PublicServerError",
    "InvalidRequestError",
    "AuthenticationRequiredError",
    "RouteAccessDeniedError",
    "RateLimitExceededError",
    "RequestConflictError",
    "InternalServerError",
    "ServiceNotConfiguredError",
    "RateLimiter",
    "FixedWindowRateLimiter",
    "make_fastapi_bearer_auth_middleware",
    "make_flask_bearer_auth_middleware",
    "make_fixed_window_rate_limiter",
    "INDEX_HTML",
]
