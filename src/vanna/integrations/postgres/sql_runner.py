"""PostgreSQL implementation of SqlRunner interface."""

import asyncio
import math
from typing import Any, Optional

import pandas as pd

from vanna.capabilities.sql_runner import (
    DEFAULT_MAX_RESULT_BYTES,
    DEFAULT_MAX_RESULT_ROWS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    RunSqlToolArgs,
    SqlRunner,
)
from vanna.capabilities.sql_runner.limits import (
    fetch_bounded_records,
    validate_execution_limits,
)
from vanna.core.tool import ToolContext
from vanna.security.sql_policy import ReadOnlySqlPolicy


class PostgresRunner(SqlRunner):
    """PostgreSQL implementation of the SqlRunner interface."""

    dialect = "postgres"

    def __init__(
        self,
        connection_string: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = 5432,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        read_only: bool = True,
        max_result_rows: int = DEFAULT_MAX_RESULT_ROWS,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> None:
        """Initialize with PostgreSQL connection parameters.

        You can either provide a connection_string OR individual parameters (host, database, etc.).
        If connection_string is provided, it takes precedence.

        Args:
            connection_string: PostgreSQL connection string (e.g., "postgresql://user:password@host:port/database")
            host: Database host address
            port: Database port (default: 5432)
            database: Database name
            user: Database user
            password: Database password
            read_only: Enforce read-only at the transaction level (default).
                ``False`` is the explicit privileged setup/migration path.
            **kwargs: Additional psycopg2 connection parameters (sslmode, connect_timeout, etc.)
        """
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
        self.statement_timeout_ms = max(
            1,
            math.ceil(self.query_timeout_seconds * 1_000),
        )
        self._read_only_policy = ReadOnlySqlPolicy(self.dialect)
        try:
            import psycopg2  # type: ignore[import-untyped]
            import psycopg2.extras  # type: ignore[import-untyped]

            self.psycopg2 = psycopg2
        except Exception as e:
            raise ImportError(
                "psycopg2 package is required. Install with: pip install 'vanna[postgres]'"
            ) from e

        self.connection_string: Optional[str]
        self.connection_params: Optional[dict[str, Any]]
        if connection_string:
            self.connection_string = connection_string
            self.connection_params = None
        elif host and database and user:
            self.connection_string = None
            self.connection_params = {
                "host": host,
                "port": port,
                "database": database,
                "user": user,
                "password": password,
                **kwargs,
            }
        else:
            raise ValueError(
                "Either provide connection_string OR (host, database, and user) parameters"
            )

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        """Execute SQL query against PostgreSQL database and return results as DataFrame.

        Args:
            args: SQL query arguments
            context: Tool execution context

        Returns:
            DataFrame with query results

        Raises:
            psycopg2.Error: If query execution fails
        """
        if self.read_only:
            self._read_only_policy.validate(args.sql)
        del context
        return await asyncio.to_thread(self._run_sql_sync, args)

    def _run_sql_sync(self, args: RunSqlToolArgs) -> pd.DataFrame:
        """Run blocking psycopg2 work in the worker selected by ``run_sql``."""

        if self.connection_string:
            conn = self.psycopg2.connect(self.connection_string)
        else:
            if self.connection_params is None:
                raise RuntimeError(
                    "PostgreSQL connection parameters are not configured"
                )
            conn = self.psycopg2.connect(**self.connection_params)

        try:
            cursor = conn.cursor(cursor_factory=self.psycopg2.extras.RealDictCursor)
            try:
                if self.read_only:
                    cursor.execute("BEGIN TRANSACTION READ ONLY")
                cursor.execute(
                    "SET LOCAL statement_timeout = %s",
                    (self.statement_timeout_ms,),
                )

                cursor.execute(args.sql)
                if cursor.description is not None:
                    records = fetch_bounded_records(
                        cursor,
                        row_converter=lambda row: row,
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
            finally:
                cursor.close()

        finally:
            try:
                if self.read_only:
                    conn.rollback()
            finally:
                conn.close()
