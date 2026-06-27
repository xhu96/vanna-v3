"""SQLite implementation of SqlRunner interface."""

import sqlite3
import pandas as pd

from vanna.capabilities.sql_runner import SqlRunner, RunSqlToolArgs
from vanna.core.tool import ToolContext


class SqliteRunner(SqlRunner):
    """SQLite implementation of the SqlRunner interface."""

    def __init__(self, database_path: str, read_only: bool = True):
        """Initialize with a SQLite database path.

        Args:
            database_path: Path to the SQLite database file
            read_only: Open the database read-only at the driver level (default).
        """
        self.database_path = database_path
        self.read_only = read_only

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
        # Connect to the database
        if self.read_only:
            # Open the database read-only at the driver level (defense in depth).
            conn = sqlite3.connect(
                f"file:{self.database_path}?mode=ro", uri=True
            )
        else:
            conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        cursor = conn.cursor()

        try:
            # Execute the query
            cursor.execute(args.sql)

            # Decide how to handle results based on whether the statement
            # produced a result set, not on the first keyword. `cursor.description`
            # is set for any statement that returns rows -- SELECT, WITH ... SELECT,
            # PRAGMA, EXPLAIN, etc. -- and is None for pure writes (INSERT/UPDATE/
            # DELETE). Keying off the first keyword instead would silently discard
            # the output of read-only statements like WITH/PRAGMA/EXPLAIN.
            if cursor.description is not None:
                # Fetch results for any statement that returned a result set.
                rows = cursor.fetchall()
                if not rows:
                    # Return empty DataFrame
                    return pd.DataFrame()

                # Convert rows to list of dictionaries
                results_data = [dict(row) for row in rows]
                return pd.DataFrame(results_data)
            else:
                # For statements that did not return a result set (INSERT,
                # UPDATE, DELETE, etc.) report the affected-row count.
                conn.commit()
                rows_affected = cursor.rowcount
                # Return a DataFrame indicating rows affected
                return pd.DataFrame({"rows_affected": [rows_affected]})

        finally:
            cursor.close()
            conn.close()
