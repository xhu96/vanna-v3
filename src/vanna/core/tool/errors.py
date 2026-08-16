"""Public-safe tool failure envelopes."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def public_tool_failure(
    *,
    operation: str,
    code: str,
    error: BaseException,
) -> tuple[str, dict[str, Any]]:
    """Return a correlation-coded message without serializing the exception."""

    correlation_id = f"tool_{uuid.uuid4().hex}"
    logger.error(
        "Tool operation failed operation=%s code=%s correlation_id=%s error_type=%s",
        operation,
        code,
        correlation_id,
        type(error).__name__,
    )
    return (
        f"{operation} failed. Correlation ID: {correlation_id}.",
        {
            "error_type": code,
            "correlation_id": correlation_id,
        },
    )


__all__ = ["public_tool_failure"]
