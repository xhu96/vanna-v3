"""Security tests for read-only SQL enforcement."""

import pandas as pd
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.tools.run_sql import RunSqlTool


class DummySqlRunner(SqlRunner):
    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        return pd.DataFrame([{"ok": 1}])


@pytest.fixture
def tool_context():
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="conv1",
        request_id="req1",
        agent_memory=DemoAgentMemory(),
    )


def _make_tool_context():
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )


@pytest.mark.asyncio
async def test_run_sql_blocks_write_statement_by_default(tool_context):
    tool = RunSqlTool(sql_runner=DummySqlRunner())
    result = await tool.execute(tool_context, RunSqlToolArgs(sql="DELETE FROM users"))
    assert result.success is False
    assert "read-only SQL policy" in result.result_for_llm


@pytest.mark.asyncio
async def test_run_sql_blocks_multi_statement_by_default(tool_context):
    tool = RunSqlTool(sql_runner=DummySqlRunner())
    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1; SELECT 2;"))
    assert result.success is False
    assert "Multiple SQL statements are blocked" in result.result_for_llm


@pytest.mark.asyncio
async def test_run_sql_allows_select_in_read_only_mode(tool_context):
    tool = RunSqlTool(sql_runner=DummySqlRunner())
    result = await tool.execute(tool_context, RunSqlToolArgs(sql="SELECT 1"))
    assert result.success is True


class _NullRunner:
    async def run_sql(self, args, context):
        import pandas as pd
        return pd.DataFrame()


def _tool():
    return RunSqlTool(sql_runner=_NullRunner(), read_only=True)


def test_blocks_data_modifying_cte():
    err = _tool()._validate_read_only_sql(
        "WITH t AS (DELETE FROM users RETURNING *) SELECT * FROM t"
    )
    assert err is not None


def test_blocks_stacked_statement_with_drop():
    err = _tool()._validate_read_only_sql("SELECT 1; DROP TABLE users")
    assert err is not None


def test_blocks_unparseable_sql_fail_closed():
    err = _tool()._validate_read_only_sql("this is not sql )(")
    assert err is not None


def test_allows_read_only_cte():
    err = _tool()._validate_read_only_sql(
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t"
    )
    assert err is None


def test_blocks_update_statement():
    err = _tool()._validate_read_only_sql("UPDATE users SET name = 'x'")
    assert err is not None


def test_blocks_select_into_new_table():
    # SELECT ... INTO is a DDL/write in Postgres/MSSQL; it parses as an
    # exp.Select with an exp.Into child and must be blocked.
    err = _tool()._validate_read_only_sql("SELECT * INTO new_table FROM users")
    assert err is not None


def test_blocks_explain_analyze_delete():
    # EXPLAIN ANALYZE actually executes the wrapped statement in Postgres, and
    # the DELETE is hidden inside an opaque exp.Command literal.
    err = _tool()._validate_read_only_sql("EXPLAIN ANALYZE DELETE FROM users")
    assert err is not None


def test_blocks_explain_analyze_select():
    # EXPLAIN ANALYZE executes the query even for a plain SELECT payload.
    err = _tool()._validate_read_only_sql("EXPLAIN ANALYZE SELECT * FROM users")
    assert err is not None


def test_blocks_explain_delete():
    # A write hidden inside an EXPLAIN command literal must be rejected.
    err = _tool()._validate_read_only_sql("EXPLAIN DELETE FROM users")
    assert err is not None


def test_allows_plain_explain_select():
    # Plain EXPLAIN of a read-only query stays allowed.
    err = _tool()._validate_read_only_sql("EXPLAIN SELECT * FROM users")
    assert err is None


@pytest.mark.asyncio
async def test_cte_select_returns_rows_not_rows_affected():
    import pandas as pd

    class _OneRowRunner:
        async def run_sql(self, args, context):
            return pd.DataFrame([{"x": 1}])

    tool = RunSqlTool(sql_runner=_OneRowRunner(), read_only=True)

    class _Ctx:
        pass

    # minimal context stub with a file_system; reuse the tool's default
    result = await tool.execute(_make_tool_context(), RunSqlToolArgs(sql="WITH t AS (SELECT 1 AS x) SELECT x FROM t"))
    assert result.success is True
    assert "row(s) affected" not in result.result_for_llm
    assert result.metadata["query_type"] == "WITH"
    assert result.metadata.get("row_count") == 1


@pytest.fixture
def sqlite_db(tmp_path):
    """A small on-disk SQLite database with a single table `t` holding 3 rows."""
    import sqlite3

    db_path = tmp_path / "fixture.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t (x) VALUES (?)", [(1,), (2,), (3,)])
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.mark.asyncio
async def test_real_sqlite_runner_with_select_returns_all_rows(sqlite_db, tmp_path):
    """End-to-end against the real SqliteRunner: a read-only WITH ... SELECT must
    return its full result set, not a 'rows_affected' placeholder. This guards the
    runner routing bug where non-SELECT first keywords discarded real rows."""
    from vanna.integrations.local import LocalFileSystem
    from vanna.integrations.sqlite.sql_runner import SqliteRunner

    tool = RunSqlTool(
        sql_runner=SqliteRunner(sqlite_db, read_only=True),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        read_only=True,
    )

    result = await tool.execute(
        _make_tool_context(),
        RunSqlToolArgs(sql="WITH q AS (SELECT x FROM t) SELECT x FROM q"),
    )

    assert result.success is True
    assert "row(s) affected" not in result.result_for_llm
    assert result.metadata["query_type"] == "WITH"
    assert result.metadata["row_count"] == 3
    assert result.metadata["columns"] == ["x"]
    assert "rows_affected" not in result.metadata["columns"]


@pytest.mark.asyncio
async def test_real_sqlite_runner_pragma_returns_result_set(sqlite_db, tmp_path):
    """End-to-end against the real SqliteRunner: PRAGMA is read-only and returns a
    result set; it must not be collapsed into a 'rows_affected' DataFrame."""
    from vanna.integrations.local import LocalFileSystem
    from vanna.integrations.sqlite.sql_runner import SqliteRunner

    tool = RunSqlTool(
        sql_runner=SqliteRunner(sqlite_db, read_only=True),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        read_only=True,
    )

    result = await tool.execute(
        _make_tool_context(),
        RunSqlToolArgs(sql="PRAGMA table_info(t)"),
    )

    assert result.success is True
    assert "row(s) affected" not in result.result_for_llm
    assert result.metadata["query_type"] == "PRAGMA"
    # PRAGMA table_info returns one row per column with the standard schema columns.
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
async def test_real_sqlite_runner_plain_select_still_returns_rows(sqlite_db, tmp_path):
    """Regression guard: plain SELECT continues to return its full result set."""
    from vanna.integrations.local import LocalFileSystem
    from vanna.integrations.sqlite.sql_runner import SqliteRunner

    tool = RunSqlTool(
        sql_runner=SqliteRunner(sqlite_db, read_only=True),
        file_system=LocalFileSystem(working_directory=str(tmp_path)),
        read_only=True,
    )

    result = await tool.execute(
        _make_tool_context(),
        RunSqlToolArgs(sql="SELECT x FROM t"),
    )

    assert result.success is True
    assert result.metadata["query_type"] == "SELECT"
    assert result.metadata["row_count"] == 3
    assert result.metadata["columns"] == ["x"]
