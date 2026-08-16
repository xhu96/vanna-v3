"""Hermetic regressions for dialect-aware read-only SQL enforcement."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.sqlite import SqliteRunner
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import (
    ReadOnlySqlPolicy,
    SqlPolicyViolation,
    SqlQueryPolicy,
)
from vanna.tools.run_sql import RunSqlTool
from vanna.tools.file_system import LocalFileSystem as ToolLocalFileSystem


class RecordingPostgresRunner(SqlRunner):
    dialect = "postgres"
    native_read_only = True

    def __init__(self, rows_affected: bool = False) -> None:
        self.calls: List[str] = []
        self.rows_affected = rows_affected

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        self.calls.append(args.sql)
        if self.rows_affected:
            return pd.DataFrame({"rows_affected": [1]})
        return pd.DataFrame([{"ok": 1}])


class LegacyV2Runner(SqlRunner):
    def __init__(self) -> None:
        self.calls: List[str] = []

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        self.calls.append(args.sql)
        return pd.DataFrame([{"ok": 1}])


class SecretFailingRunner(SqlRunner):
    dialect = "postgres"
    native_read_only = True

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        raise RuntimeError(
            "connection failed for postgresql://admin:secret-password@internal/db"
        )


@pytest.fixture
def tool_context() -> ToolContext:
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="conv1",
        request_id="req1",
        agent_memory=DemoAgentMemory(),
    )


@pytest.fixture
def sqlite_db(tmp_path: Path) -> str:
    db_path = tmp_path / "fixture.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t (x) VALUES (?)", [(1,), (2,), (3,)])
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users(id) VALUES (1)",
        "UPDATE users SET name = 'x'",
        "DELETE FROM users",
        "MERGE INTO users USING incoming ON users.id = incoming.id "
        "WHEN MATCHED THEN UPDATE SET name = incoming.name",
        "TRUNCATE TABLE users",
        "CREATE TABLE copy (id INT)",
        "ALTER TABLE users ADD COLUMN secret TEXT",
        "DROP TABLE users",
        "GRANT SELECT ON users TO public",
        "WITH removed AS (DELETE FROM users RETURNING *) SELECT * FROM removed",
        "WITH changed AS (UPDATE users SET name = 'x' RETURNING *) "
        "SELECT * FROM changed",
        "WITH added AS (INSERT INTO users(id) VALUES (1) RETURNING *) "
        "SELECT * FROM added",
        "SELECT * INTO copied_users FROM users",
        "SELECT * FROM users FOR UPDATE",
        "SELECT * FROM users FOR NO KEY UPDATE",
        "SELECT * FROM users FOR SHARE",
        "COPY users TO STDOUT",
        "COPY (SELECT * FROM users) TO PROGRAM 'cat >/tmp/users'",
        "EXPLAIN SELECT * FROM users",
        "EXPLAIN ANALYZE SELECT * FROM users",
        "EXPLAIN (ANALYZE, BUFFERS) DELETE FROM users",
        "VACUUM users",
        "ANALYZE users",
        "CALL rotate_keys()",
        "DO $$ BEGIN DELETE FROM users; END $$",
        "SHOW search_path",
        "SET search_path = public",
        "RESET ALL",
        "LISTEN updates",
        "NOTIFY updates",
        "LOCK TABLE users IN ACCESS EXCLUSIVE MODE",
        "REFRESH MATERIALIZED VIEW user_rollup",
        "TABLE users",
        "VALUES (1)",
    ],
)
def test_postgres_policy_blocks_writes_locks_and_vendor_commands(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation):
        ReadOnlySqlPolicy("postgres").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT nextval('user_id_seq')",
        "SELECT pg_catalog.nextval('user_id_seq')",
        "SELECT setval('user_id_seq', 10)",
        "SELECT currval('user_id_seq')",
        "SELECT lastval()",
        "SELECT set_config('search_path', 'public', false)",
        "SELECT pg_notify('events', 'payload')",
        "SELECT pg_advisory_lock(42)",
        "SELECT pg_try_advisory_lock(42)",
        "SELECT lo_export(42, '/tmp/blob')",
        "SELECT * FROM dblink('remote', 'DELETE FROM users RETURNING id') "
        "AS result(id int)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/passwd')",
        "SELECT * FROM pg_ls_dir('/var/lib/postgresql')",
    ],
)
def test_postgres_policy_blocks_stateful_functions(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation, match="function"):
        ReadOnlySqlPolicy("postgres").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT count(*) FROM users WHERE active = true",
        "WITH active AS (SELECT id FROM users WHERE active) SELECT * FROM active",
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 3) "
        "SELECT x FROM n",
        "WITH constants AS (VALUES (1), (2)) SELECT * FROM constants",
        "SELECT 1 UNION ALL SELECT 2",
        "(SELECT 1)",
        "SELECT 1; -- one statement with a trailing comment\n",
    ],
)
def test_postgres_policy_retains_select_compatibility(sql: str) -> None:
    ReadOnlySqlPolicy("postgres").validate(sql)


def test_unknown_functions_require_an_explicit_allowlist() -> None:
    with pytest.raises(SqlPolicyViolation, match="not allowlisted"):
        ReadOnlySqlPolicy("postgres").validate("SELECT custom_write_udf()")
    ReadOnlySqlPolicy(
        "postgres", allowed_functions={"approved_business_metric"}
    ).validate("SELECT approved_business_metric()")


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA table_info(t)",
        'PRAGMA main.table_info("t")',
        "PRAGMA table_xinfo('t')",
        "PRAGMA index_list(t)",
        "PRAGMA index_info(index_t_x)",
        "PRAGMA index_xinfo(index_t_x)",
        "PRAGMA foreign_key_list(t)",
        "PRAGMA database_list",
        "PRAGMA database_list()",
        "PRAGMA compile_options",
        "PRAGMA collation_list",
        "PRAGMA journal_mode",
        "PRAGMA query_only",
        "PRAGMA schema_version",
        "PRAGMA page_count",
        "PRAGMA foreign_key_check",
        "PRAGMA foreign_key_check(t)",
        "PRAGMA table_list",
        "PRAGMA table_list(t)",
    ],
)
def test_sqlite_policy_allows_only_allowlisted_informational_pragmas(
    sql: str,
) -> None:
    ReadOnlySqlPolicy("sqlite").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA user_version",
        "PRAGMA user_version = 1",
        "PRAGMA journal_mode = WAL",
        "PRAGMA journal_mode(WAL)",
        "PRAGMA wal_checkpoint",
        "PRAGMA wal_checkpoint(TRUNCATE)",
        "PRAGMA query_only = OFF",
        "PRAGMA query_only(OFF)",
        "PRAGMA query_only = ON",
        "PRAGMA writable_schema",
        "PRAGMA writable_schema = ON",
        "PRAGMA optimize",
        "PRAGMA incremental_vacuum",
        "PRAGMA incremental_vacuum(10)",
        "PRAGMA foreign_keys = OFF",
        "PRAGMA table_info = t",
        "PRAGMA table_info()",
        "PRAGMA application_id",
        "PRAGMA definitely_unknown",
        "SELECT * FROM pragma_table_info('t')",
        "SELECT load_extension('/tmp/evil')",
        "SELECT writefile('/tmp/export', 'secret')",
        "ATTACH DATABASE '/tmp/other.db' AS other",
        "DETACH DATABASE other",
        "VACUUM",
    ],
)
def test_sqlite_policy_rejects_mutating_or_unknown_forms(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation):
        ReadOnlySqlPolicy("sqlite").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "/*!50000 DROP TABLE users */",
        "SELECT 1 /*!50000 INTO OUTFILE '/tmp/users' */",
        "SELECT 1--2 /*!50000 + SLEEP(10) */",
        "SELECT 1 /*M!100100 SET @x = 1 */",
        "SELECT /*+ SET_VAR(foreign_key_checks=OFF) */ 1",
        "SELECT * INTO OUTFILE '/tmp/users' FROM users",
        "SELECT @x := 1",
        "SELECT id INTO @x FROM users",
        "SELECT get_lock('vanna', 10)",
        "SELECT release_lock('vanna')",
        "SELECT last_insert_id(5)",
        "SELECT load_file('/etc/passwd')",
        "LOCK TABLES users WRITE",
        "SHOW TABLES",
        "DESCRIBE users",
        "USE production",
        "SET @x = 1",
        "CALL mutate_users()",
    ],
)
def test_mysql_policy_blocks_executable_comments_exports_and_state(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation):
        ReadOnlySqlPolicy("mysql").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT `name` FROM `users`",
        "WITH active AS (SELECT id FROM users) SELECT * FROM active",
        "SELECT 1 /* ordinary inert comment */",
        "SELECT '/*! literal text, not a comment */' AS text",
    ],
)
def test_mysql_policy_retains_select_compatibility(sql: str) -> None:
    ReadOnlySqlPolicy("mysql").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_text('/etc/passwd')",
        "SELECT * FROM read_blob('/var/run/secrets/token')",
        "SELECT * FROM read_csv_auto('/tmp/private.csv')",
        "SELECT * FROM read_json('https://attacker.invalid/data.json')",
        "SELECT * FROM read_parquet('s3://private-bucket/data.parquet')",
        "SELECT * FROM parquet_scan('/tmp/private.parquet')",
        "SELECT * FROM sqlite_scan('/tmp/foreign.db', 'users')",
        "SELECT * FROM postgres_scan('host=internal', 'public', 'users')",
        "SELECT * FROM mysql_query('mysql://internal', 'SELECT secret FROM users')",
        "SELECT * FROM delta_scan('/tmp/table')",
        "SELECT * FROM iceberg_scan('s3://private/table')",
        "SELECT * FROM st_read('/tmp/private.geojson')",
        "SELECT glob('/home/*/.ssh/*')",
        "SELECT * FROM query('SELECT * FROM read_text(''/etc/passwd'')')",
    ],
)
def test_duckdb_policy_blocks_external_resources_and_dynamic_queries(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation, match="external resource"):
        ReadOnlySqlPolicy("duckdb").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT count(*) FROM local_table",
        "WITH local_rows AS (SELECT id FROM local_table) SELECT * FROM local_rows",
        "SELECT range AS value FROM range(3)",
    ],
)
def test_duckdb_policy_retains_local_select_compatibility(sql: str) -> None:
    ReadOnlySqlPolicy("duckdb").validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE users",
        "this is not SQL )(",
        "/* comment only */",
    ],
)
def test_policy_fails_closed_on_empty_stacked_or_unparseable_sql(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation):
        ReadOnlySqlPolicy("postgres").validate(sql)


def test_policy_rejects_unknown_or_unsupported_dialect() -> None:
    with pytest.raises(ValueError, match="explicit supported"):
        ReadOnlySqlPolicy("unknown")
    with pytest.raises(ValueError, match="Unsupported SQL dialect"):
        ReadOnlySqlPolicy("made-up-vendor")


def test_dialect_is_applied_instead_of_generic_parser() -> None:
    ReadOnlySqlPolicy("mysql").validate("SELECT `name` FROM `users`")
    with pytest.raises(SqlPolicyViolation):
        ReadOnlySqlPolicy("postgres").validate("SELECT `name` FROM `users`")


def test_legacy_statement_allowlist_can_narrow_but_not_widen_policy() -> None:
    select_only = ReadOnlySqlPolicy("postgres", {"SELECT"})
    select_only.validate("SELECT 1")
    with pytest.raises(SqlPolicyViolation):
        select_only.validate("WITH q AS (SELECT 1) SELECT * FROM q")

    delete_only = ReadOnlySqlPolicy("postgres", {"DELETE"})
    with pytest.raises(SqlPolicyViolation):
        delete_only.validate("DELETE FROM users")


@pytest.mark.asyncio
async def test_default_tool_blocks_write_before_runner(
    tool_context: ToolContext, tmp_path: Path
) -> None:
    runner = RecordingPostgresRunner()
    tool = RunSqlTool(
        sql_runner=runner,
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
    )

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="DELETE FROM users"))

    assert result.success is False
    assert result.metadata["error_type"] == "sql_security_violation"
    assert runner.calls == []


@pytest.mark.asyncio
async def test_tool_derives_known_runner_dialect_and_allows_select(
    tool_context: ToolContext, tmp_path: Path
) -> None:
    runner = RecordingPostgresRunner()
    tool = RunSqlTool(
        sql_runner=runner,
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        query_policy=SqlQueryPolicy("postgres", require_row_policies=False),
    )

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))

    assert result.success is True
    assert tool.dialect == "postgres"
    assert runner.calls == ["SELECT 1"]


@pytest.mark.asyncio
async def test_tool_rejects_over_budget_custom_runner_results_before_serialization(
    tool_context: ToolContext,
    tmp_path: Path,
) -> None:
    class OversizedRunner(RecordingPostgresRunner):
        async def run_sql(
            self,
            args: RunSqlToolArgs,
            context: ToolContext,
        ) -> pd.DataFrame:
            del args, context
            return pd.DataFrame([{"value": 1}, {"value": 2}])

    tool = RunSqlTool(
        sql_runner=OversizedRunner(),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        query_policy=SqlQueryPolicy("postgres", require_row_policies=False),
        max_result_rows=1,
    )

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))

    assert result.success is False
    assert result.metadata["error_type"] == "query_execution_failed"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_tool_applies_context_row_policies_before_runner(
    tool_context: ToolContext, tmp_path: Path
) -> None:
    runner = RecordingPostgresRunner()
    tool_context.metadata["sql_row_policies"] = [
        RowFilterPolicy(
            column="tenant_id",
            value="tenant-a",
            tables=frozenset({"orders"}),
        )
    ]
    tool = RunSqlTool(
        sql_runner=runner,
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
    )

    result = await tool.execute(
        tool_context, RunSqlToolArgs(sql="SELECT id FROM orders")
    )

    assert result.success is True
    assert len(runner.calls) == 1
    assert "tenant_id = 'tenant-a'" in runner.calls[0]
    assert result.metadata["executed_sql"] == runner.calls[0]


@pytest.mark.asyncio
async def test_required_query_policy_fails_closed_without_tenant_policy(
    tool_context: ToolContext,
) -> None:
    runner = RecordingPostgresRunner()
    tool = RunSqlTool(
        sql_runner=runner,
        query_policy=SqlQueryPolicy("postgres"),
    )

    result = await tool.execute(
        tool_context, RunSqlToolArgs(sql="SELECT id FROM orders")
    )

    assert result.success is False
    assert "required tenant policies are missing" in result.result_for_llm
    assert runner.calls == []


@pytest.mark.asyncio
async def test_unknown_legacy_runner_fails_closed_until_dialect_is_injected(
    tool_context: ToolContext, tmp_path: Path
) -> None:
    runner = LegacyV2Runner()
    assert runner.dialect == "unknown"
    assert runner.native_read_only is False

    unresolved = RunSqlTool(
        sql_runner=runner,
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        require_native_read_only=False,
    )
    blocked = await unresolved.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))
    assert blocked.success is False
    assert "dialect is unknown" in blocked.result_for_llm
    assert runner.calls == []

    resolved = RunSqlTool(
        sql_runner=runner,
        query_policy=SqlQueryPolicy("postgres", require_row_policies=False),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        require_native_read_only=False,
    )
    allowed = await resolved.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))
    assert allowed.success is True
    assert resolved.dialect == "postgres"
    assert runner.calls == ["SELECT 1"]


@pytest.mark.asyncio
async def test_explicit_query_policy_supplies_legacy_runner_dialect(
    tool_context: ToolContext,
) -> None:
    runner = LegacyV2Runner()
    tool = RunSqlTool(
        sql_runner=runner,
        query_policy=SqlQueryPolicy("postgres", require_row_policies=False),
        require_native_read_only=False,
    )

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))

    assert result.success is True
    assert tool.dialect == "postgres"
    assert runner.calls == ["SELECT 1"]


@pytest.mark.asyncio
async def test_row_policy_provider_is_resolved_once_per_execution(
    tool_context: ToolContext,
) -> None:
    runner = RecordingPostgresRunner()
    calls = 0

    def policies(context: ToolContext):
        nonlocal calls
        calls += 1
        assert context is tool_context
        return [
            RowFilterPolicy(
                column="tenant_id",
                value="tenant-a",
                tables=frozenset({"orders"}),
            )
        ]

    tool = RunSqlTool(
        sql_runner=runner,
        query_policy=SqlQueryPolicy("postgres", row_policies=policies),
    )
    result = await tool.execute(
        tool_context, RunSqlToolArgs(sql="SELECT id FROM orders")
    )

    assert result.success is True
    assert calls == 1
    assert "tenant_id = 'tenant-a'" in runner.calls[0]


@pytest.mark.asyncio
async def test_default_tool_rejects_runner_without_native_read_only(
    tool_context: ToolContext,
) -> None:
    runner = LegacyV2Runner()
    tool = RunSqlTool(
        sql_runner=runner,
        query_policy=SqlQueryPolicy("postgres", require_row_policies=False),
    )

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))

    assert result.success is False
    assert "native read-only execution boundary" in result.result_for_llm
    assert runner.calls == []


def test_tool_rejects_explicit_dialect_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        RunSqlTool(sql_runner=RecordingPostgresRunner(), dialect="sqlite")


@pytest.mark.asyncio
async def test_explicit_write_mode_is_privileged_opt_in(
    tool_context: ToolContext, tmp_path: Path
) -> None:
    runner = RecordingPostgresRunner(rows_affected=True)
    default_tool = RunSqlTool(sql_runner=runner)
    blocked = await default_tool.execute(
        tool_context, RunSqlToolArgs(sql="DELETE FROM users")
    )
    assert blocked.success is False
    assert runner.calls == []

    privileged_tool = RunSqlTool(
        sql_runner=runner,
        read_only=False,
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
    )
    allowed = await privileged_tool.execute(
        tool_context, RunSqlToolArgs(sql="DELETE FROM users")
    )
    assert allowed.success is True
    assert allowed.metadata["rows_affected"] == 1
    assert runner.calls == ["DELETE FROM users"]


@pytest.mark.asyncio
async def test_privileged_tool_does_not_require_supported_custom_dialect(
    tool_context: ToolContext,
) -> None:
    runner = LegacyV2Runner()
    runner.dialect = "private-vendor"
    tool = RunSqlTool(sql_runner=runner, read_only=False)

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SETUP DATABASE"))

    assert result.success is True
    assert runner.calls == ["SETUP DATABASE"]


@pytest.mark.asyncio
async def test_real_sqlite_tool_returns_cte_rows(
    sqlite_db: str, tool_context: ToolContext, tmp_path: Path
) -> None:
    tool = RunSqlTool(
        sql_runner=SqliteRunner(sqlite_db),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        query_policy=SqlQueryPolicy("sqlite", require_row_policies=False),
    )

    result = await tool.execute(
        tool_context,
        RunSqlToolArgs(sql="WITH q AS (SELECT x FROM t) SELECT x FROM q"),
    )

    assert result.success is True
    assert result.metadata["query_type"] == "WITH"
    assert result.metadata["row_count"] == 3
    assert result.metadata["columns"] == ["x"]


@pytest.mark.asyncio
async def test_real_sqlite_tool_returns_informational_pragma_rows(
    sqlite_db: str, tool_context: ToolContext, tmp_path: Path
) -> None:
    tool = RunSqlTool(
        sql_runner=SqliteRunner(sqlite_db),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        query_policy=SqlQueryPolicy("sqlite", require_row_policies=False),
    )

    result = await tool.execute(
        tool_context, RunSqlToolArgs(sql="PRAGMA table_info(t)")
    )

    assert result.success is True
    assert result.metadata["query_type"] == "PRAGMA"
    assert result.metadata["columns"] == [
        "cid",
        "name",
        "type",
        "notnull",
        "dflt_value",
        "pk",
    ]
    assert result.metadata["row_count"] == 1


@pytest.mark.asyncio
async def test_real_sqlite_tool_never_forwards_query_only_change(
    sqlite_db: str, tool_context: ToolContext
) -> None:
    runner = SqliteRunner(sqlite_db)
    tool = RunSqlTool(sql_runner=runner)

    result = await tool.execute(
        tool_context, RunSqlToolArgs(sql="PRAGMA query_only=OFF")
    )

    assert result.success is False
    assert result.metadata["error_type"] == "sql_security_violation"


@pytest.mark.asyncio
async def test_database_exception_is_correlation_coded_and_redacted(
    tool_context: ToolContext,
) -> None:
    tool = RunSqlTool(
        sql_runner=SecretFailingRunner(),
        query_policy=SqlQueryPolicy("postgres", require_row_policies=False),
    )

    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))
    serialized = result.model_dump_json()

    assert result.success is False
    assert "Correlation ID: tool_" in result.result_for_llm
    assert "secret-password" not in serialized
    assert "postgresql://" not in serialized
    assert result.metadata["error_type"] == "query_execution_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("filesystem_type", [LocalFileSystem, ToolLocalFileSystem])
async def test_local_artifacts_isolate_same_subject_across_tenants(
    tmp_path: Path,
    filesystem_type: type[LocalFileSystem],
) -> None:
    filesystem = filesystem_type(working_directory=str(tmp_path))
    tenant_a = ToolContext(
        user=User(id="shared", metadata={"tenant_id": "a"}),
        conversation_id="conv-a",
        request_id="req-a",
        agent_memory=DemoAgentMemory(),
    )
    tenant_b = tenant_a.model_copy(
        update={
            "user": User(id="shared", metadata={"tenant_id": "b"}),
            "conversation_id": "conv-b",
            "request_id": "req-b",
        }
    )

    await filesystem.write_file("result.csv", "tenant-a", tenant_a)

    assert await filesystem.exists("result.csv", tenant_a)
    assert not await filesystem.exists("result.csv", tenant_b)
