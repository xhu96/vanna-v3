"""DuckDB implementation of SqlRunner interface."""

import asyncio
import threading
from typing import Any, Optional

import pandas as pd

from vanna.capabilities.sql_runner import (
    DEFAULT_MAX_RESULT_BYTES,
    DEFAULT_MAX_RESULT_ROWS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    RunSqlToolArgs,
    SqlQueryTimeoutError,
    SqlRunner,
)
from vanna.capabilities.sql_runner.limits import (
    fetch_bounded_records,
    validate_execution_limits,
)
from vanna.core.tool import ToolContext
from vanna.security.sql_policy import ReadOnlySqlPolicy


class DuckDBRunner(SqlRunner):
    """DuckDB implementation with bounded, non-blocking query execution."""

    dialect = "duckdb"

    def __init__(
        self,
        database_path: str = ":memory:",
        init_sql: Optional[str] = None,
        read_only: bool = True,
        *,
        max_result_rows: int = DEFAULT_MAX_RESULT_ROWS,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> None:
        """Initialize a DuckDB connection and secure execution limits."""
        try:
            import duckdb  # type: ignore[import-not-found]

            self.duckdb = duckdb
        except ImportError as exc:
            raise ImportError(
                "duckdb package is required. Install with: pip install 'vanna[duckdb]'"
            ) from exc

        self.database_path = database_path
        self.init_sql = init_sql
        self.read_only = read_only
        self.native_read_only = read_only and database_path not in {
            ":memory:",
            "md:",
            "motherduck:",
        }
        self.kwargs = dict(kwargs)
        if self.native_read_only:
            configured_read_only = self.kwargs.setdefault("read_only", True)
            if configured_read_only is not True:
                raise ValueError(
                    "read_only connection mode cannot be disabled implicitly"
                )
        (
            self.max_result_rows,
            self.max_result_bytes,
            self.query_timeout_seconds,
        ) = validate_execution_limits(
            max_result_rows,
            max_result_bytes,
            query_timeout_seconds,
        )
        self.query_policy = ReadOnlySqlPolicy(self.dialect)
        if self.read_only and self.init_sql:
            self.query_policy.validate(self.init_sql)
        self._conn: Any = None
        self._connection_lock = threading.RLock()

    def _get_connection(self) -> Any:
        """Get or create the process-local DuckDB connection."""
        if self._conn is None:
            self._conn = self.duckdb.connect(self.database_path, **self.kwargs)
            if self.init_sql:
                self._conn.execute(self.init_sql)
        return self._conn

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        """Validate policy and execute blocking DuckDB work in a worker thread."""
        if self.read_only:
            self.query_policy.validate(args.sql)
        del context
        return await asyncio.to_thread(self._run_sql_sync, args)

    def _run_sql_sync(self, args: RunSqlToolArgs) -> pd.DataFrame:
        """Execute one serialized query with interrupt and materialization bounds."""
        with self._connection_lock:
            conn = self._get_connection()
            timed_out = threading.Event()
            finished = threading.Event()

            def interrupt_query() -> None:
                if finished.is_set():
                    return
                timed_out.set()
                try:
                    conn.interrupt()
                except Exception:
                    # The deadline remains authoritative even if a driver rejects
                    # an interrupt racing with normal query completion.
                    pass

            timer = threading.Timer(self.query_timeout_seconds, interrupt_query)
            timer.daemon = True
            timer.start()
            try:
                cursor = conn.execute(args.sql)
                if cursor.description is not None:
                    columns = self._column_names(cursor.description)
                    records = fetch_bounded_records(
                        cursor,
                        row_converter=lambda row: dict(zip(columns, row)),
                        max_result_rows=self.max_result_rows,
                        max_result_bytes=self.max_result_bytes,
                    )
                    result = pd.DataFrame.from_records(records, columns=columns)
                else:
                    result = pd.DataFrame({"rows_affected": [cursor.rowcount]})

                finished.set()
                if timed_out.is_set():
                    raise SqlQueryTimeoutError(
                        "SQL query exceeded the configured timeout"
                    )
                return result
            except Exception:
                finished.set()
                if timed_out.is_set():
                    raise SqlQueryTimeoutError(
                        "SQL query exceeded the configured timeout"
                    ) from None
                raise
            finally:
                finished.set()
                timer.cancel()
                timer.join()

    @staticmethod
    def _column_names(description: Any) -> list[str]:
        """Create stable unique DataFrame names for duplicate result columns."""
        counts: dict[str, int] = {}
        names: list[str] = []
        for index, descriptor in enumerate(description, start=1):
            base_name = str(descriptor[0] or f"column_{index}")
            count = counts.get(base_name, 0) + 1
            counts[base_name] = count
            names.append(base_name if count == 1 else f"{base_name}_{count}")
        return names
