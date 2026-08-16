"""Shared execution and materialization limits for SQL runners."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

DEFAULT_MAX_RESULT_ROWS = 5_000
DEFAULT_MAX_RESULT_BYTES = 2 * 1024 * 1024
DEFAULT_QUERY_TIMEOUT_SECONDS = 30.0
_FETCH_BATCH_SIZE = 256


class SqlResultLimitError(RuntimeError):
    """Raised when a SQL result exceeds its configured materialization budget."""


class SqlQueryTimeoutError(TimeoutError):
    """Raised when a driver-enforced SQL deadline expires."""


def validate_execution_limits(
    max_result_rows: int,
    max_result_bytes: int,
    query_timeout_seconds: float,
) -> tuple[int, int, float]:
    """Normalize finite positive execution limits."""

    if isinstance(max_result_rows, bool) or not isinstance(max_result_rows, int):
        raise ValueError("max_result_rows must be an integer")
    if max_result_rows < 1:
        raise ValueError("max_result_rows must be positive")
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int):
        raise ValueError("max_result_bytes must be an integer")
    if max_result_bytes < 1:
        raise ValueError("max_result_bytes must be positive")
    if isinstance(query_timeout_seconds, bool) or not isinstance(
        query_timeout_seconds, (int, float)
    ):
        raise ValueError("query_timeout_seconds must be numeric")
    timeout = float(query_timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("query_timeout_seconds must be finite and positive")
    return max_result_rows, max_result_bytes, timeout


def _value_size(value: Any, *, depth: int = 0) -> int:
    if depth > 8:
        raise SqlResultLimitError("SQL result contains an unsupported nested value")
    if value is None:
        return 4
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (bool, int, float, Decimal, date, datetime)):
        return len(str(value).encode("utf-8"))
    if isinstance(value, Mapping):
        return sum(
            len(str(key).encode("utf-8")) + _value_size(item, depth=depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return sum(_value_size(item, depth=depth + 1) for item in value)
    return len(str(value).encode("utf-8"))


def _record_size(record: Mapping[str, Any]) -> int:
    return 2 + sum(
        len(str(key).encode("utf-8")) + _value_size(value) + 4
        for key, value in record.items()
    )


def fetch_bounded_records(
    cursor: Any,
    *,
    row_converter: Callable[[Any], Mapping[str, Any]],
    max_result_rows: int,
    max_result_bytes: int,
) -> list[dict[str, Any]]:
    """Fetch in small batches and reject overflow before DataFrame construction."""

    records: list[dict[str, Any]] = []
    materialized_bytes = 0
    while True:
        batch = cursor.fetchmany(_FETCH_BATCH_SIZE)
        if not batch:
            break
        for row in batch:
            if len(records) >= max_result_rows:
                raise SqlResultLimitError("SQL result exceeds the configured row limit")
            record = dict(row_converter(row))
            materialized_bytes += _record_size(record)
            if materialized_bytes > max_result_bytes:
                raise SqlResultLimitError(
                    "SQL result exceeds the configured byte limit"
                )
            records.append(record)
    return records


def enforce_dataframe_limits(
    dataframe: pd.DataFrame,
    *,
    max_result_rows: int,
    max_result_bytes: int,
) -> None:
    """Apply a defensive bound to results returned by custom runners."""

    if len(dataframe.index) > max_result_rows:
        raise SqlResultLimitError("SQL result exceeds the configured row limit")
    columns = [str(column) for column in dataframe.columns]
    materialized_bytes = 0
    for values in dataframe.itertuples(index=False, name=None):
        materialized_bytes += _record_size(dict(zip(columns, values)))
        if materialized_bytes > max_result_bytes:
            raise SqlResultLimitError("SQL result exceeds the configured byte limit")


__all__ = [
    "DEFAULT_MAX_RESULT_BYTES",
    "DEFAULT_MAX_RESULT_ROWS",
    "DEFAULT_QUERY_TIMEOUT_SECONDS",
    "SqlQueryTimeoutError",
    "SqlResultLimitError",
    "enforce_dataframe_limits",
    "fetch_bounded_records",
    "validate_execution_limits",
]
