"""
SQL runner capability.

This module provides abstractions for SQL execution used by tools.
"""

from .base import SqlRunner
from .limits import (
    DEFAULT_MAX_RESULT_BYTES,
    DEFAULT_MAX_RESULT_ROWS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    SqlQueryTimeoutError,
    SqlResultLimitError,
)
from .models import RunSqlToolArgs

__all__ = [
    "SqlRunner",
    "RunSqlToolArgs",
    "DEFAULT_MAX_RESULT_BYTES",
    "DEFAULT_MAX_RESULT_ROWS",
    "DEFAULT_QUERY_TIMEOUT_SECONDS",
    "SqlQueryTimeoutError",
    "SqlResultLimitError",
]
