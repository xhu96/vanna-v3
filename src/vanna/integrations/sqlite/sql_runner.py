"""SQLite implementation of SqlRunner interface."""

import asyncio
import sqlite3
import time
from pathlib import Path

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


class SqliteRunner(SqlRunner):
    """SQLite implementation of the SqlRunner interface."""

    dialect = "sqlite"

    def __init__(
        self,
        database_path: str,
        read_only: bool = True,
        *,
        max_result_rows: int = DEFAULT_MAX_RESULT_ROWS,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize with a SQLite database path.

        Args:
            database_path: Path to the SQLite database file
            read_only: Open the database read-only at the driver level (default).
                ``False`` is the explicit privileged setup/migration path.
        """
        self.database_path = database_path
        self.read_only = read_only
        self.native_read_only = read_only
        (
            self.max_result_rows,
            self.max_result_bytes,
            self.query_timeout_seconds,
        ) = validate_execution_limits(
            max_result_rows,
            max_result_bytes,
            query_timeout_seconds,
        )
        self._read_only_policy = ReadOnlySqlPolicy(self.dialect)

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        """Execute SQL query against SQLite database and return results as DataFrame.

        Args:
            args: SQL query arguments
            context: Tool execution context

        Returns:
            DataFrame with query results

        Raises:
            sqlite3.Error: If query execution fails
        """
        if self.read_only:
            self._read_only_policy.validate(args.sql)
        del context
        return await asyncio.to_thread(self._run_sql_sync, args)

    def _run_sql_sync(self, args: RunSqlToolArgs) -> pd.DataFrame:
        """Run blocking sqlite3 work in the worker selected by ``run_sql``."""

        target, use_uri = (
            self._read_only_target()
            if self.read_only
            else (self.database_path, self.database_path.startswith("file:"))
        )
        conn = sqlite3.connect(
            target,
            uri=use_uri,
            timeout=self.query_timeout_seconds,
        )
        deadline = time.monotonic() + self.query_timeout_seconds
        timed_out = False

        def interrupt_after_deadline() -> int:
            nonlocal timed_out
            if time.monotonic() >= deadline:
                timed_out = True
                return 1
            return 0

        try:
            conn.set_progress_handler(interrupt_after_deadline, 1_000)
            if self.read_only:
                conn.execute("PRAGMA query_only=ON").close()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(args.sql)
                if cursor.description is not None:
                    records = fetch_bounded_records(
                        cursor,
                        row_converter=dict,
                        max_result_rows=self.max_result_rows,
                        max_result_bytes=self.max_result_bytes,
                    )
                    if not records:
                        result = pd.DataFrame()
                    else:
                        result = pd.DataFrame(records)
                else:
                    result = pd.DataFrame({"rows_affected": [cursor.rowcount]})

                if not self.read_only:
                    conn.commit()
                return result
            except sqlite3.OperationalError:
                if timed_out:
                    raise SqlQueryTimeoutError(
                        "SQL query exceeded the configured timeout"
                    ) from None
                raise
            finally:
                cursor.close()
        finally:
            try:
                conn.set_progress_handler(None, 0)
                if self.read_only:
                    conn.rollback()
            finally:
                conn.close()

    def _read_only_target(self) -> tuple[str, bool]:
        """Build a read-only SQLite URI when the database has a disk path."""

        normalized_path = self.database_path.lower()
        if (
            normalized_path == ":memory:"
            or normalized_path.startswith("file::memory:")
            or "mode=memory" in normalized_path
        ):
            return self.database_path, self.database_path.startswith("file:")

        if self.database_path.startswith("file:"):
            base, _, query = self.database_path.partition("?")
            params = [
                item
                for item in query.split("&")
                if item and not item.lower().startswith("mode=")
            ]
            params.append("mode=ro")
            return f"{base}?{'&'.join(params)}", True

        uri = Path(self.database_path).expanduser().resolve().as_uri()
        return f"{uri}?mode=ro", True
