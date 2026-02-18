"""
Base server components for the Vanna Agents framework.

This module provides framework-agnostic components for handling chat
requests and responses.
"""

from .chat_handler import ChatHandler
from .models import ChatRequest, ChatStreamChunk, ChatResponse
from .events_v3 import ChatEvent
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
    "make_fastapi_bearer_auth_middleware",
    "make_flask_bearer_auth_middleware",
    "make_fixed_window_rate_limiter",
    "INDEX_HTML",
]
