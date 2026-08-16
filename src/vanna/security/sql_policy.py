"""Dialect-aware, fail-closed policy for untrusted read-only SQL."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, Collection, Iterable, Optional, Union

import sqlglot
from sqlglot import Dialect, ErrorLevel, exp

from .rls import RowFilterPolicy, apply_row_policies

if TYPE_CHECKING:
    from vanna.core.tool import ToolContext


class SqlPolicyViolation(ValueError):
    """Raised when SQL is not provably safe under the read-only policy."""


_DIALECT_ALIASES = {
    "mssql": "tsql",
    "postgresql": "postgres",
}

_MYSQL_EXECUTABLE_COMMENT_MARKER = re.compile(r"\s*(?:!|\+|M\s*!)", re.IGNORECASE)

_SQLITE_IDENTIFIER = (
    r'(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")*"|'
    r"`(?:[^`]|``)*`|\[(?:[^\]]|\]\])*\])"
)
_SQLITE_PRAGMA_ARGUMENT = rf"(?:{_SQLITE_IDENTIFIER}|'(?:[^']|'')*')"
_SQLITE_PRAGMA = re.compile(
    rf"""
    \A\s*PRAGMA\s+
    (?:(?P<schema>{_SQLITE_IDENTIFIER})\s*\.\s*)?
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    (?P<arguments>\s*\(\s*(?P<argument>{_SQLITE_PRAGMA_ARGUMENT})?\s*\))?
    \s*;?\s*\Z
    """,
    re.IGNORECASE | re.VERBOSE,
)

# These forms only report connection or database metadata when called without an
# argument. Assignment and argument forms are rejected by the grammar above.
_SQLITE_NO_ARGUMENT_PRAGMAS = frozenset(
    {
        "collation_list",
        "compile_options",
        "database_list",
        "data_version",
        "encoding",
        "foreign_keys",
        "freelist_count",
        "function_list",
        "integrity_check",
        "journal_mode",
        "module_list",
        "page_count",
        "pragma_list",
        "query_only",
        "quick_check",
        "schema_version",
    }
)
_SQLITE_REQUIRED_IDENTIFIER_PRAGMAS = frozenset(
    {
        "foreign_key_list",
        "index_info",
        "index_list",
        "index_xinfo",
        "table_info",
        "table_xinfo",
    }
)
_SQLITE_OPTIONAL_IDENTIFIER_PRAGMAS = frozenset(
    {
        "foreign_key_check",
        "table_list",
    }
)

# A SELECT can still invoke functions that mutate database/session state or the
# host. Native read-only transactions remain the primary backstop; this list
# blocks known high-risk built-ins before they reach the driver.
_SIDE_EFFECT_FUNCTIONS = frozenset(
    {
        "brin_summarize_new_values",
        "currval",
        "dblink",
        "dblink_exec",
        "eval",
        "get_lock",
        "gin_clean_pending_list",
        "last_insert_id",
        "lastval",
        "load_extension",
        "load_file",
        "lo_export",
        "lo_import",
        "nextval",
        "pg_advisory_lock",
        "pg_advisory_lock_shared",
        "pg_advisory_unlock",
        "pg_advisory_unlock_all",
        "pg_advisory_unlock_shared",
        "pg_cancel_backend",
        "pg_create_restore_point",
        "pg_log_backend_memory_contexts",
        "pg_notify",
        "pg_promote",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_switch_wal",
        "pg_terminate_backend",
        "pg_try_advisory_lock",
        "pg_try_advisory_lock_shared",
        "pg_wal_replay_pause",
        "pg_wal_replay_resume",
        "pg_stat_file",
        "release_all_locks",
        "release_lock",
        "set_config",
        "setseed",
        "setval",
        "sys_eval",
        "sys_exec",
        "uuid_short",
        "writefile",
    }
)
_SIDE_EFFECT_FUNCTION_PREFIXES = (
    "dblink_",
    "lo_",
    "pg_advisory_",
    "pg_backup_",
    "pg_copy_logical_replication_slot",
    "pg_create_logical_replication_slot",
    "pg_create_physical_replication_slot",
    "pg_drop_replication_slot",
    "pg_ls_",
    "pg_read_",
    "pg_replication_origin_",
    "pg_start_backup",
    "pg_stop_backup",
    "pragma_",
)

_DUCKDB_EXTERNAL_RESOURCE_FUNCTIONS = frozenset(
    {
        "delta_scan",
        "glob",
        "http_get",
        "http_post",
        "iceberg_metadata",
        "iceberg_scan",
        "iceberg_snapshots",
        "mysql_query",
        "mysql_scan",
        "parquet_scan",
        "postgres_query",
        "postgres_scan",
        "postgres_scan_pushdown",
        "query",
        "query_table",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_json_objects_auto",
        "read_ndjson",
        "read_ndjson_auto",
        "read_ndjson_objects",
        "read_parquet",
        "read_text",
        "read_xlsx",
        "shapefile_meta",
        "sqlite_query",
        "sqlite_scan",
        "st_read",
        "st_read_osm",
    }
)
_DUCKDB_EXTERNAL_RESOURCE_PREFIXES = (
    "delta_",
    "iceberg_",
    "mysql_",
    "postgres_",
    "read_",
    "sqlite_",
    "st_read",
)

_UNSAFE_QUERY_NODES = (
    exp.DDL,
    exp.DML,
    exp.Attach,
    exp.Copy,
    exp.Detach,
    exp.Execute,
    exp.Export,
    exp.Into,
    exp.LoadData,
    exp.Lock,
    exp.Pragma,
    exp.Set,
    exp.Transaction,
    exp.Use,
)


def normalize_sql_dialect(dialect: str) -> str:
    """Return the sqlglot dialect name used for policy parsing."""

    normalized = dialect.strip().lower() if dialect else "unknown"
    return _DIALECT_ALIASES.get(normalized, normalized)


def _contains_mysql_executable_comment(sql: str) -> bool:
    """Find executable block comments while ignoring quoted string contents."""

    index = 0
    quote: Optional[str] = None
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        dash_comment = sql.startswith("--", index) and (
            index + 2 == len(sql) or sql[index + 2].isspace()
        )
        if dash_comment or char == "#":
            newline = sql.find("\n", index + 1)
            index = len(sql) if newline == -1 else newline + 1
            continue
        if sql.startswith("/*", index):
            marker_start = index + 2
            if _MYSQL_EXECUTABLE_COMMENT_MARKER.match(sql, marker_start):
                return True
            comment_end = sql.find("*/", marker_start)
            index = len(sql) if comment_end == -1 else comment_end + 2
            continue
        index += 1
    return False


class ReadOnlySqlPolicy:
    """Prove that one SQL statement is a read-only query for a known dialect."""

    def __init__(
        self,
        dialect: str,
        allowed_statement_types: Optional[Collection[str]] = None,
        *,
        allowed_functions: Optional[Collection[str]] = None,
        allow_unknown_functions: bool = False,
    ) -> None:
        self.dialect = normalize_sql_dialect(dialect)
        if self.dialect in {"", "unknown"}:
            raise ValueError(
                "Read-only SQL policy requires an explicit supported SQL dialect."
            )
        try:
            Dialect.get_or_raise(self.dialect)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported SQL dialect for read-only policy: {dialect!r}."
            ) from exc

        self.allowed_statement_types = (
            None
            if allowed_statement_types is None
            else frozenset(value.strip().upper() for value in allowed_statement_types)
        )
        self.allowed_functions = frozenset(
            value.strip().lower()
            for value in (allowed_functions or ())
            if value.strip()
        )
        self.allow_unknown_functions = allow_unknown_functions

    def validate(self, sql: str) -> None:
        """Raise ``SqlPolicyViolation`` unless ``sql`` is provably read-only."""

        if not sql or not sql.strip():
            raise SqlPolicyViolation("SQL query cannot be empty.")

        if self.dialect in {
            "mysql",
            "singlestore",
        } and _contains_mysql_executable_comment(sql):
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: executable MySQL comments are "
                "not allowed."
            )

        statement = self._parse_one(sql)
        nodes = tuple(statement.walk())

        if any(isinstance(node, exp.Command) for node in nodes):
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: opaque SQL commands are not allowed."
            )

        if isinstance(statement, exp.Pragma):
            self._validate_sqlite_pragma(sql)
            self._validate_legacy_statement_type("PRAGMA")
            return

        if any(isinstance(node, _UNSAFE_QUERY_NODES) for node in nodes):
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: a write, lock, or state-changing "
                "SQL construct was detected."
            )

        if self.dialect in {"mysql", "singlestore"} and any(
            isinstance(node, exp.PropertyEQ) for node in nodes
        ):
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: session-variable assignment is "
                "not allowed."
            )

        if not self._is_select_query(statement):
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: only parsed SELECT queries and "
                "approved SQLite informational PRAGMAs are allowed."
            )

        self._validate_functions(nodes)
        statement_type = "WITH" if statement.args.get("with_") else "SELECT"
        self._validate_legacy_statement_type(statement_type)

    def validation_error(self, sql: str) -> Optional[str]:
        """Return a policy error message, or ``None`` when validation succeeds."""

        try:
            self.validate(sql)
        except SqlPolicyViolation as exc:
            return str(exc)
        return None

    def _parse_one(self, sql: str) -> exp.Expr:
        try:
            parsed = sqlglot.parse(
                sql,
                read=self.dialect,
                error_level=ErrorLevel.RAISE,
            )
        except Exception as exc:
            raise SqlPolicyViolation(
                f"SQL could not be parsed as {self.dialect!r} and is blocked by "
                "the read-only SQL policy."
            ) from exc

        statements = [
            statement
            for statement in parsed
            if statement is not None and not isinstance(statement, exp.Semicolon)
        ]
        if not statements:
            raise SqlPolicyViolation("SQL query cannot be empty.")
        if len(statements) != 1:
            raise SqlPolicyViolation(
                "Multiple SQL statements are blocked by the read-only SQL policy."
            )
        return statements[0]

    def _validate_sqlite_pragma(self, sql: str) -> None:
        if self.dialect != "sqlite":
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: PRAGMA is only supported for SQLite."
            )

        match = _SQLITE_PRAGMA.fullmatch(sql)
        if match is None:
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy: SQLite PRAGMA must use an "
                "approved non-assignment informational form."
            )

        name = match.group("name").lower()
        has_parentheses = match.group("arguments") is not None
        has_argument = match.group("argument") is not None

        if name in _SQLITE_NO_ARGUMENT_PRAGMAS:
            allowed_shape = not has_argument
        elif name in _SQLITE_REQUIRED_IDENTIFIER_PRAGMAS:
            allowed_shape = has_parentheses and has_argument
        elif name in _SQLITE_OPTIONAL_IDENTIFIER_PRAGMAS:
            allowed_shape = not has_parentheses or has_argument
        else:
            allowed_shape = False

        if not allowed_shape:
            raise SqlPolicyViolation(
                f"Blocked by read-only SQL policy: SQLite PRAGMA {name!r} is "
                "unknown, mutating, or has an unsafe argument shape."
            )

    def _validate_functions(self, nodes: Iterable[exp.Expr]) -> None:
        for node in nodes:
            if not isinstance(node, exp.Func):
                continue
            name = (
                node.name
                if isinstance(node, exp.Anonymous)
                else node.sql_name().lower()
            )
            normalized = name.lower()
            if self.dialect == "duckdb" and (
                normalized in _DUCKDB_EXTERNAL_RESOURCE_FUNCTIONS
                or normalized.endswith("_scan")
                or normalized.startswith(_DUCKDB_EXTERNAL_RESOURCE_PREFIXES)
            ):
                raise SqlPolicyViolation(
                    "Blocked by read-only SQL policy: DuckDB external resource, "
                    "dynamic query, and connector functions are not allowed."
                )
            if normalized in _SIDE_EFFECT_FUNCTIONS or normalized.startswith(
                _SIDE_EFFECT_FUNCTION_PREFIXES
            ):
                raise SqlPolicyViolation(
                    "Blocked by read-only SQL policy: stateful or side-effect "
                    f"function {normalized!r} is not allowed."
                )
            if (
                isinstance(node, exp.Anonymous)
                and not self.allow_unknown_functions
                and normalized not in self.allowed_functions
            ):
                raise SqlPolicyViolation(
                    "Blocked by read-only SQL policy: unknown or user-defined "
                    f"function {normalized!r} is not allowlisted."
                )

    def _validate_legacy_statement_type(self, statement_type: str) -> None:
        if (
            self.allowed_statement_types is not None
            and statement_type not in self.allowed_statement_types
        ):
            allowed = ", ".join(sorted(self.allowed_statement_types)) or "none"
            raise SqlPolicyViolation(
                "Blocked by read-only SQL policy. Allowed statement types were "
                f"narrowed to: {allowed}."
            )

    @classmethod
    def _is_select_query(cls, statement: exp.Expr) -> bool:
        if isinstance(statement, exp.Select):
            return True
        if isinstance(statement, exp.Subquery):
            return cls._is_select_query(statement.this)
        if isinstance(statement, exp.SetOperation):
            return cls._is_select_query(statement.this) and cls._is_select_query(
                statement.expression
            )
        return False


RowPolicyProvider = Callable[["ToolContext"], Iterable[RowFilterPolicy]]
RowPolicySource = Union[Iterable[RowFilterPolicy], RowPolicyProvider]


class SqlQueryPolicy:
    """Apply one read-only and row-security boundary before SQL execution."""

    def __init__(
        self,
        dialect: str,
        *,
        row_policies: Optional[RowPolicySource] = None,
        require_row_policies: bool = True,
        allowed_unfiltered_tables: Collection[str] = (),
        allowed_statement_types: Optional[Collection[str]] = None,
        allowed_functions: Optional[Collection[str]] = None,
        allow_unknown_functions: bool = False,
    ) -> None:
        self.dialect = normalize_sql_dialect(dialect)
        self.read_only = ReadOnlySqlPolicy(
            self.dialect,
            allowed_statement_types=allowed_statement_types,
            allowed_functions=allowed_functions,
            allow_unknown_functions=allow_unknown_functions,
        )
        self.row_policies = row_policies
        self.require_row_policies = require_row_policies
        self.allowed_unfiltered_tables = tuple(allowed_unfiltered_tables)

    def prepare(self, sql: str, context: Optional["ToolContext"] = None) -> str:
        """Return policy-approved SQL or raise ``SqlPolicyViolation``."""

        self.read_only.validate(sql)
        policies = self._resolve_row_policies(context)
        if self.require_row_policies and not policies:
            raise SqlPolicyViolation(
                "Blocked by SQL row policy: required tenant policies are missing."
            )
        if not policies:
            return sql

        try:
            prepared = apply_row_policies(
                sql,
                policies,
                dialect=self.dialect,
                allowed_unfiltered_tables=self.allowed_unfiltered_tables,
            )
        except (TypeError, ValueError) as exc:
            raise SqlPolicyViolation(
                "Blocked by SQL row policy: query sources could not be safely "
                "constrained."
            ) from exc
        self.read_only.validate(prepared)
        return prepared

    def validation_error(
        self, sql: str, context: Optional["ToolContext"] = None
    ) -> Optional[str]:
        try:
            self.prepare(sql, context)
        except SqlPolicyViolation as exc:
            return str(exc)
        return None

    def _resolve_row_policies(
        self, context: Optional["ToolContext"]
    ) -> tuple[RowFilterPolicy, ...]:
        source = self.row_policies
        if source is None and context is not None:
            source = context.metadata.get("sql_row_policies")
        if source is None:
            return ()
        if callable(source):
            if context is None:
                raise SqlPolicyViolation(
                    "Blocked by SQL row policy: execution context is required."
                )
            try:
                source = source(context)
            except SqlPolicyViolation:
                raise
            except Exception:
                raise SqlPolicyViolation(
                    "Blocked by SQL row policy: policy resolution failed."
                ) from None
        try:
            policies = tuple(source)
        except Exception:
            raise SqlPolicyViolation(
                "Blocked by SQL row policy: configured policies are invalid."
            ) from None
        if not all(isinstance(policy, RowFilterPolicy) for policy in policies):
            raise SqlPolicyViolation(
                "Blocked by SQL row policy: configured policies are invalid."
            )
        return policies
