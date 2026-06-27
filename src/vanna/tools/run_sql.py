"""Generic SQL query execution tool with dependency injection."""

from typing import Any, Dict, List, Optional, Type, cast, Set
import uuid
import sqlparse
import sqlglot
from sqlglot import expressions as exp
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.components import (
    UiComponent,
    DataFrameComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)
from vanna.capabilities.sql_runner import SqlRunner, RunSqlToolArgs
from vanna.capabilities.file_system import FileSystem
from vanna.integrations.local import LocalFileSystem


# Any of these appearing anywhere in the parsed tree means the statement
# mutates data/schema — including inside CTEs — and must be blocked.
# `exp.Into` covers `SELECT ... INTO new_table` (a DDL/write in Postgres/MSSQL)
# which otherwise parses as an exp.Select with an exp.Into child and would slip
# past a write-expression scan.
_WRITE_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Into,
)


class RunSqlTool(Tool[RunSqlToolArgs]):
    """Tool that executes SQL queries using an injected SqlRunner implementation."""

    def __init__(
        self,
        sql_runner: SqlRunner,
        file_system: Optional[FileSystem] = None,
        custom_tool_name: Optional[str] = None,
        custom_tool_description: Optional[str] = None,
        read_only: bool = True,
        allowed_statement_types: Optional[Set[str]] = None,
    ):
        """Initialize the tool with a SqlRunner implementation.

        Args:
            sql_runner: SqlRunner implementation that handles actual query execution
            file_system: FileSystem implementation for saving results (defaults to LocalFileSystem)
            custom_tool_name: Optional custom name for the tool (overrides default "run_sql")
            custom_tool_description: Optional custom description for the tool (overrides default description)
            read_only: Whether to enforce read-only SQL statements (secure default)
            allowed_statement_types: Allowed first SQL keywords when read_only=True
        """
        self.sql_runner = sql_runner
        self.file_system = file_system or LocalFileSystem()
        self._custom_name = custom_tool_name
        self._custom_description = custom_tool_description
        self.read_only = read_only
        self.allowed_statement_types = allowed_statement_types or {
            "SELECT",
            "WITH",
            "SHOW",
            "DESCRIBE",
            "DESC",
            "EXPLAIN",
            "PRAGMA",
        }

    @property
    def name(self) -> str:
        return self._custom_name if self._custom_name else "run_sql"

    @property
    def description(self) -> str:
        return (
            self._custom_description
            if self._custom_description
            else "Execute SQL queries against the configured database"
        )

    def get_args_schema(self) -> Type[RunSqlToolArgs]:
        return RunSqlToolArgs

    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        """Execute a SQL query using the injected SqlRunner."""
        try:
            if self.read_only:
                validation_error = self._validate_read_only_sql(args.sql)
                if validation_error:
                    return ToolResult(
                        success=False,
                        result_for_llm=validation_error,
                        ui_component=UiComponent(
                            rich_component=NotificationComponent(
                                type=ComponentType.NOTIFICATION,
                                level="error",
                                message=validation_error,
                            ),
                            simple_component=SimpleTextComponent(text=validation_error),
                        ),
                        error=validation_error,
                        metadata={
                            "error_type": "sql_security_violation",
                            "executed_sql": args.sql,
                            "validation_checks": ["read_only_policy_failed"],
                        },
                    )

            # Use the injected SqlRunner to execute the query
            df = await self.sql_runner.run_sql(args, context)

            query_type = args.sql.strip().upper().split()[0]

            # Read-only statements (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN/PRAGMA) all return
            # result sets. Treat any returned DataFrame as results; only when running in
            # write mode (read_only=False) and the runner reports an affected-row count
            # do we render the write acknowledgement.
            is_write_result = (
                not self.read_only
                and not df.empty
                and list(df.columns) == ["rows_affected"]
            )

            if is_write_result:
                rows_affected = int(df["rows_affected"].iloc[0])
                result = f"Query executed successfully. {rows_affected} row(s) affected."
                metadata = {
                    "rows_affected": rows_affected,
                    "query_type": query_type,
                    "executed_sql": args.sql,
                    "validation_checks": ["read_only_policy_passed"],
                }
                ui_component = UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION, level="success", message=result
                    ),
                    simple_component=SimpleTextComponent(text=result),
                )
            elif df.empty:
                result = "Query executed successfully. No rows returned."
                ui_component = UiComponent(
                    rich_component=DataFrameComponent(
                        rows=[], columns=[], title="Query Results", description="No rows returned"
                    ),
                    simple_component=SimpleTextComponent(text=result),
                )
                metadata = {
                    "row_count": 0,
                    "columns": [],
                    "query_type": query_type,
                    "results": [],
                }
            else:
                results_data = df.to_dict("records")
                columns = df.columns.tolist()
                row_count = len(df)

                file_id = str(uuid.uuid4())[:8]
                filename = f"query_results_{file_id}.csv"
                csv_content = df.to_csv(index=False)
                await self.file_system.write_file(filename, csv_content, context, overwrite=True)

                results_preview = csv_content
                if len(results_preview) > 1000:
                    results_preview = (
                        results_preview[:1000]
                        + "\n(Results truncated to 1000 characters. FOR LARGE RESULTS YOU DO NOT NEED TO SUMMARIZE THESE RESULTS OR PROVIDE OBSERVATIONS. THE NEXT STEP SHOULD BE A VISUALIZE_DATA CALL)"
                    )
                result = f"{results_preview}\n\nResults saved to file: {filename}\n\n**IMPORTANT: FOR VISUALIZE_DATA USE FILENAME: {filename}**"

                dataframe_component = DataFrameComponent.from_records(
                    records=cast(List[Dict[str, Any]], results_data),
                    title="Query Results",
                    description=f"SQL query returned {row_count} rows with {len(columns)} columns",
                )
                ui_component = UiComponent(
                    rich_component=dataframe_component,
                    simple_component=SimpleTextComponent(text=result),
                )
                metadata = {
                    "row_count": row_count,
                    "columns": columns,
                    "query_type": query_type,
                    "results": results_data,
                    "output_file": filename,
                    "executed_sql": args.sql,
                    "validation_checks": ["read_only_policy_passed"],
                }

            return ToolResult(
                success=True,
                result_for_llm=result,
                ui_component=ui_component,
                metadata=metadata,
            )

        except Exception as e:
            error_message = f"Error executing query: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=str(e),
                metadata={"error_type": "sql_error", "executed_sql": args.sql},
            )

    def _validate_read_only_sql(self, sql: str) -> Optional[str]:
        """Validate SQL against the read-only policy using AST parsing.

        Defense in depth: parse the statement, reject multiple statements,
        reject anything that mutates data/schema anywhere in the tree
        (covers data-modifying CTEs), and require the top-level keyword to be
        in the read-only allowlist. Fails closed on parse errors.
        """
        if not sql or not sql.strip():
            return "SQL query cannot be empty."

        try:
            statements = [s for s in sqlglot.parse(sql) if s is not None]
        except Exception:
            return "SQL could not be parsed and is blocked by the read-only policy."

        if not statements:
            return "SQL query cannot be empty."
        if len(statements) > 1:
            return "Multiple SQL statements are blocked by default."

        statement = statements[0]
        if statement.find(*_WRITE_EXPRESSIONS) is not None:
            return "Blocked by read-only SQL policy: a data-modifying statement was detected."

        # sqlglot falls back to an opaque exp.Command node for syntax it cannot
        # model (e.g. `EXPLAIN ANALYZE ...`), stashing the remainder as a string
        # literal. A write buried in that literal escapes the AST scan above, and
        # EXPLAIN ANALYZE actually executes the statement in Postgres. Re-parse
        # the trailing payload and fail closed on anything that is not a plain
        # read.
        command_block = self._validate_command_payload(statement)
        if command_block is not None:
            return command_block

        first_keyword = sql.strip().split(None, 1)[0].upper()
        if first_keyword not in self.allowed_statement_types:
            allowed_list = ", ".join(sorted(self.allowed_statement_types))
            return (
                f"Blocked by read-only SQL policy. "
                f"Allowed statement types: {allowed_list}."
            )
        return None

    def _validate_command_payload(self, statement: exp.Expression) -> Optional[str]:
        """Inspect opaque exp.Command nodes for hidden writes.

        sqlglot models statements it cannot fully parse as an exp.Command whose
        keyword is in `this` and whose remainder is stuffed into a string literal
        (e.g. `EXPLAIN ANALYZE DELETE FROM users` -> Command(this='EXPLAIN',
        expression='ANALYZE DELETE FROM users')). A data-modifying statement
        hidden in that literal is invisible to the AST write scan, so re-parse
        the payload and fail closed on anything that is not a plain read.
        Returns an error string when the command must be blocked, else None.
        """
        if not isinstance(statement, exp.Command):
            return None

        keyword = (statement.this or "").strip().upper()
        expression = statement.args.get("expression")
        payload = expression.this if isinstance(expression, exp.Literal) else ""
        payload = (payload or "").strip()

        # EXPLAIN ANALYZE actually executes the statement in Postgres, so it is a
        # write vector regardless of the wrapped query. Block it outright.
        if keyword == "EXPLAIN" and payload.upper().startswith("ANALYZE"):
            return (
                "Blocked by read-only SQL policy: EXPLAIN ANALYZE executes the "
                "statement and is not read-only."
            )

        # For EXPLAIN/DESCRIBE-style commands, re-parse the wrapped statement and
        # reject it if it mutates data/schema. Fail closed if the payload cannot
        # be parsed.
        if keyword in {"EXPLAIN", "DESCRIBE", "DESC"} and payload:
            try:
                inner = [s for s in sqlglot.parse(payload) if s is not None]
            except Exception:
                return (
                    "Blocked by read-only SQL policy: the wrapped statement could "
                    "not be parsed."
                )
            for inner_stmt in inner:
                if isinstance(inner_stmt, exp.Command):
                    nested = self._validate_command_payload(inner_stmt)
                    if nested is not None:
                        return nested
                if inner_stmt.find(*_WRITE_EXPRESSIONS) is not None or isinstance(
                    inner_stmt, _WRITE_EXPRESSIONS
                ):
                    return (
                        "Blocked by read-only SQL policy: a data-modifying "
                        "statement was detected."
                    )
        return None
