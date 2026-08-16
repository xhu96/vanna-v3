"""Generic SQL query execution tool with dependency injection."""

import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Set, Type, cast

from vanna.core.tool import (
    PRIVILEGED_SQL_WRITE_CAPABILITY,
    Tool,
    ToolContext,
    ToolResult,
)
from vanna.core.tool.errors import public_tool_failure
from vanna.components import (
    UiComponent,
    DataFrameComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)
from vanna.capabilities.sql_runner import (
    DEFAULT_MAX_RESULT_BYTES,
    DEFAULT_MAX_RESULT_ROWS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    RunSqlToolArgs,
    SqlRunner,
)
from vanna.capabilities.sql_runner.limits import (
    enforce_dataframe_limits,
    validate_execution_limits,
)
from vanna.capabilities.file_system import FileSystem
from vanna.integrations.local import LocalFileSystem
from vanna.security.sql_policy import (
    SqlPolicyViolation,
    SqlQueryPolicy,
    normalize_sql_dialect,
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
        dialect: Optional[str] = None,
        query_policy: Optional[SqlQueryPolicy] = None,
        require_native_read_only: bool = True,
        max_result_rows: int = DEFAULT_MAX_RESULT_ROWS,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
    ) -> None:
        """Initialize the tool with a SqlRunner implementation.

        Args:
            sql_runner: SqlRunner implementation that handles actual query execution
            file_system: FileSystem implementation for saving results (defaults to LocalFileSystem)
            custom_tool_name: Optional custom name for the tool (overrides default "run_sql")
            custom_tool_description: Optional custom description for the tool (overrides default description)
            read_only: Whether to enforce read-only SQL statements (secure
                default). ``False`` exposes the runner's privileged writable
                path and must not be used for a default agent tool.
            allowed_statement_types: Legacy compatibility option that can only
                narrow the shared read-only policy.
            dialect: Explicit sqlglot dialect. When omitted, a known runner
                dialect is derived; legacy runners reporting ``unknown`` must
                inject this value before read-only SQL can execute.
            require_native_read_only: Require a runner-declared native read-only
                boundary. Set ``False`` only for an explicit legacy migration
                backed by an externally enforced least-privilege DB credential.
        """
        self.sql_runner = sql_runner
        self.file_system = file_system or LocalFileSystem()
        self._custom_name = custom_tool_name
        self._custom_description = custom_tool_description
        self.read_only = read_only
        self.allowed_statement_types = allowed_statement_types
        self.require_native_read_only = require_native_read_only
        self.max_result_rows, self.max_result_bytes, _ = validate_execution_limits(
            max_result_rows,
            max_result_bytes,
            DEFAULT_QUERY_TIMEOUT_SECONDS,
        )

        reported_dialect = getattr(sql_runner, "dialect", "unknown")
        runner_dialect = normalize_sql_dialect(
            reported_dialect if isinstance(reported_dialect, str) else "unknown"
        )
        explicit_dialect = (
            normalize_sql_dialect(dialect) if dialect is not None else None
        )
        if (
            explicit_dialect is not None
            and runner_dialect != "unknown"
            and explicit_dialect != runner_dialect
        ):
            raise ValueError(
                "RunSqlTool dialect does not match the injected runner dialect: "
                f"{explicit_dialect!r} != {runner_dialect!r}."
            )

        self.dialect = explicit_dialect or (
            query_policy.dialect
            if query_policy is not None and runner_dialect == "unknown"
            else runner_dialect
        )
        if query_policy is not None and query_policy.dialect != self.dialect:
            raise ValueError(
                "RunSqlTool query policy dialect does not match the runner dialect: "
                f"{query_policy.dialect!r} != {self.dialect!r}."
            )
        self.query_policy = (
            None
            if not self.read_only or self.dialect == "unknown"
            else query_policy
            or SqlQueryPolicy(
                self.dialect,
                require_row_policies=True,
                allowed_statement_types=allowed_statement_types,
            )
        )
        self.read_only_policy = (
            self.query_policy.read_only if self.query_policy is not None else None
        )

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

    @property
    def capabilities(self) -> FrozenSet[str]:
        capabilities = {"sql"}
        if not self.read_only:
            capabilities.add(PRIVILEGED_SQL_WRITE_CAPABILITY)
        return frozenset(capabilities)

    def get_args_schema(self) -> Type[RunSqlToolArgs]:
        return RunSqlToolArgs

    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        """Execute a SQL query using the injected SqlRunner."""
        try:
            if self.read_only:
                if self.require_native_read_only and (
                    getattr(self.sql_runner, "native_read_only", False) is not True
                ):
                    validation_error = (
                        "Blocked by read-only SQL policy: the runner does not "
                        "declare a native read-only execution boundary. Configure "
                        "a read-only runner/DB role or explicitly opt into the "
                        "legacy compatibility override."
                    )
                    prepared_sql = None
                elif self.query_policy is None:
                    validation_error = (
                        "Blocked by read-only SQL policy: the runner dialect is "
                        "unknown. Configure RunSqlTool(dialect=...) or expose "
                        "SqlRunner.dialect."
                    )
                    prepared_sql = None
                else:
                    try:
                        prepared_sql = self.query_policy.prepare(args.sql, context)
                        validation_error = None
                    except SqlPolicyViolation as exc:
                        prepared_sql = None
                        validation_error = str(exc)
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
                            "dialect": self.dialect,
                            "row_count": 0,
                            "validation_checks": ["read_only_policy_failed"],
                        },
                    )
                if prepared_sql is None:
                    raise ValueError("Read-only SQL query was not prepared")
                args = args.model_copy(update={"sql": prepared_sql})

            # Use the injected SqlRunner to execute the query
            df = await self.sql_runner.run_sql(args, context)
            enforce_dataframe_limits(
                df,
                max_result_rows=self.max_result_rows,
                max_result_bytes=self.max_result_bytes,
            )

            query_type = args.sql.strip().upper().split()[0]

            # SELECT/WITH and approved PRAGMAs return result sets. Only an explicitly
            # writable tool may render a runner-reported affected-row count.
            is_write_result = (
                not self.read_only
                and not df.empty
                and list(df.columns) == ["rows_affected"]
            )

            if is_write_result:
                rows_affected = int(df["rows_affected"].iloc[0])
                result = (
                    f"Query executed successfully. {rows_affected} row(s) affected."
                )
                metadata = {
                    "rows_affected": rows_affected,
                    "query_type": query_type,
                    "executed_sql": args.sql,
                    "validation_checks": ["privileged_write_mode"],
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
                        rows=[],
                        columns=[],
                        title="Query Results",
                        description="No rows returned",
                    ),
                    simple_component=SimpleTextComponent(text=result),
                )
                metadata = {
                    "row_count": 0,
                    "columns": [],
                    "query_type": query_type,
                    "results": [],
                    "executed_sql": args.sql,
                    "dialect": self.dialect,
                    "validation_checks": ["read_only_policy_passed"],
                }
            else:
                results_data = df.to_dict("records")
                columns = df.columns.tolist()
                row_count = len(df)

                file_id = str(uuid.uuid4())[:8]
                filename = f"query_results_{file_id}.csv"
                csv_content = df.to_csv(index=False)
                await self.file_system.write_file(
                    filename, csv_content, context, overwrite=True
                )

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
                    "dialect": self.dialect,
                    "validation_checks": ["read_only_policy_passed"],
                }

            return ToolResult(
                success=True,
                result_for_llm=result,
                ui_component=ui_component,
                metadata=metadata,
            )

        except Exception as error:
            error_message, failure_metadata = public_tool_failure(
                operation="Query execution",
                code="query_execution_failed",
                error=error,
            )
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
                error=error_message,
                metadata={
                    "executed_sql": args.sql,
                    "dialect": self.dialect,
                    "row_count": 0,
                    "validation_checks": ["query_execution_failed"],
                    **failure_metadata,
                },
            )

    def _validate_read_only_sql(
        self, sql: str, context: Optional[ToolContext] = None
    ) -> Optional[str]:
        """Return the shared policy error for ``sql``, if any."""

        if self.query_policy is None:
            return (
                "Blocked by read-only SQL policy: the runner dialect is unknown. "
                "Configure RunSqlTool(dialect=...) or expose SqlRunner.dialect."
            )
        if self.require_native_read_only and (
            getattr(self.sql_runner, "native_read_only", False) is not True
        ):
            return (
                "Blocked by read-only SQL policy: the runner does not declare a "
                "native read-only execution boundary."
            )
        return self.query_policy.validation_error(sql, context)
