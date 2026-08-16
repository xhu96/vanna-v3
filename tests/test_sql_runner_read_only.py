"""Driver-level read-only enforcement tests for SQLite and PostgreSQL."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from vanna.capabilities.sql_runner import (
    DEFAULT_MAX_RESULT_BYTES,
    DEFAULT_MAX_RESULT_ROWS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    RunSqlToolArgs,
    SqlQueryTimeoutError,
    SqlResultLimitError,
    SqlRunner,
)
from vanna.integrations.bigquery import BigQueryRunner
from vanna.integrations.clickhouse import ClickHouseRunner
from vanna.integrations.duckdb import DuckDBRunner
from vanna.integrations.hive import HiveRunner
from vanna.integrations.mssql import MSSQLRunner
from vanna.integrations.mysql import MySQLRunner
from vanna.integrations.oracle import OracleRunner
from vanna.integrations.postgres import PostgresRunner
from vanna.integrations.presto import PrestoRunner
from vanna.integrations.snowflake import SnowflakeRunner
from vanna.integrations.sqlite import SqliteRunner
from vanna.security.sql_policy import ReadOnlySqlPolicy, SqlPolicyViolation


@pytest.fixture
def seeded_db(tmp_path: Path) -> str:
    path = tmp_path / "ro.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    conn.commit()
    conn.close()
    return str(path)


@pytest.mark.asyncio
async def test_sqlite_read_only_runner_allows_select(seeded_db: str) -> None:
    runner = SqliteRunner(database_path=seeded_db)

    df = await runner.run_sql(RunSqlToolArgs(sql="SELECT * FROM t"), context=None)

    assert runner.dialect == "sqlite"
    assert runner.native_read_only is True
    assert df.to_dict("records") == [{"id": 1, "name": "a"}]


@pytest.mark.asyncio
async def test_sqlite_read_only_runner_blocks_direct_write_before_driver(
    seeded_db: str,
) -> None:
    runner = SqliteRunner(database_path=seeded_db)

    with pytest.raises(SqlPolicyViolation):
        await runner.run_sql(
            RunSqlToolArgs(sql="INSERT INTO t VALUES (2, 'b')"), context=None
        )

    conn = sqlite3.connect(seeded_db)
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert count == 1


@pytest.mark.asyncio
async def test_sqlite_query_only_is_enabled_and_cannot_be_changed(
    seeded_db: str,
) -> None:
    runner = SqliteRunner(database_path=seeded_db)

    state = await runner.run_sql(RunSqlToolArgs(sql="PRAGMA query_only"), context=None)
    assert state.iloc[0, 0] == 1

    for sql in ("PRAGMA query_only=OFF", "PRAGMA query_only(OFF)"):
        with pytest.raises(SqlPolicyViolation):
            await runner.run_sql(RunSqlToolArgs(sql=sql), context=None)


@pytest.mark.asyncio
async def test_sqlite_read_only_uri_handles_reserved_path_characters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data # question?.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.execute("INSERT INTO t VALUES (7)")
    conn.commit()
    conn.close()

    runner = SqliteRunner(str(path))
    df = await runner.run_sql(RunSqlToolArgs(sql="SELECT value FROM t"), None)

    assert df.to_dict("records") == [{"value": 7}]


@pytest.mark.asyncio
async def test_sqlite_read_only_uri_overrides_writable_mode(seeded_db: str) -> None:
    configured_uri = f"{Path(seeded_db).resolve().as_uri()}?cache=private&mode=rw"
    runner = SqliteRunner(configured_uri)

    target, use_uri = runner._read_only_target()
    assert use_uri is True
    assert "mode=ro" in target
    assert "mode=rw" not in target

    df = await runner.run_sql(RunSqlToolArgs(sql="SELECT COUNT(*) AS n FROM t"), None)
    assert df.iloc[0]["n"] == 1


@pytest.mark.asyncio
async def test_sqlite_read_only_mode_does_not_create_missing_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.db"
    runner = SqliteRunner(str(path))

    with pytest.raises(sqlite3.OperationalError):
        await runner.run_sql(RunSqlToolArgs(sql="SELECT 1"), None)
    assert not path.exists()


@pytest.mark.asyncio
async def test_sqlite_explicit_writable_mode_preserves_setup_path(
    seeded_db: str,
) -> None:
    runner = SqliteRunner(database_path=seeded_db, read_only=False)

    result = await runner.run_sql(
        RunSqlToolArgs(sql="INSERT INTO t VALUES (2, 'b')"), context=None
    )

    assert runner.native_read_only is False
    assert result.iloc[0]["rows_affected"] == 1
    conn = sqlite3.connect(seeded_db)
    rows = conn.execute("SELECT id, name FROM t ORDER BY id").fetchall()
    conn.close()
    assert rows == [(1, "a"), (2, "b")]


@pytest.mark.asyncio
async def test_sqlite_writable_insert_returning_is_committed(seeded_db: str) -> None:
    runner = SqliteRunner(database_path=seeded_db, read_only=False)

    result = await runner.run_sql(
        RunSqlToolArgs(sql="INSERT INTO t VALUES (2, 'b') RETURNING id, name"),
        context=None,
    )

    assert result.to_dict("records") == [{"id": 2, "name": "b"}]
    conn = sqlite3.connect(seeded_db)
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert count == 2


@pytest.mark.asyncio
async def test_sqlite_runner_enforces_row_and_byte_budgets(seeded_db: str) -> None:
    row_limited = SqliteRunner(database_path=seeded_db, max_result_rows=1)
    with pytest.raises(SqlResultLimitError, match="row limit"):
        await row_limited.run_sql(
            RunSqlToolArgs(sql="SELECT 1 AS value UNION ALL SELECT 2 AS value"),
            None,
        )

    byte_limited = SqliteRunner(database_path=seeded_db, max_result_bytes=8)
    with pytest.raises(SqlResultLimitError, match="byte limit"):
        await byte_limited.run_sql(
            RunSqlToolArgs(sql="SELECT 'materialized-value' AS payload"),
            None,
        )


@pytest.mark.asyncio
async def test_sqlite_runner_interrupts_queries_after_deadline(seeded_db: str) -> None:
    runner = SqliteRunner(
        database_path=seeded_db,
        query_timeout_seconds=0.001,
    )
    query = (
        "WITH RECURSIVE counter(value) AS ("
        "SELECT 1 UNION ALL SELECT value + 1 FROM counter WHERE value < 100000000"
        ") SELECT SUM(value) FROM counter"
    )

    with pytest.raises(SqlQueryTimeoutError, match="configured timeout"):
        await runner.run_sql(RunSqlToolArgs(sql=query), None)


@pytest.mark.asyncio
async def test_sqlite_runner_does_not_block_the_event_loop(
    seeded_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = SqliteRunner(database_path=seeded_db)
    original = runner._run_sql_sync

    def delayed(args: RunSqlToolArgs) -> Any:
        time.sleep(0.05)
        return original(args)

    monkeypatch.setattr(runner, "_run_sql_sync", delayed)
    task = asyncio.create_task(
        runner.run_sql(RunSqlToolArgs(sql="SELECT * FROM t"), None)
    )

    await asyncio.sleep(0.01)
    assert task.done() is False
    assert (await task).to_dict("records") == [{"id": 1, "name": "a"}]


class FakePostgresCursor:
    def __init__(
        self,
        events: List[str],
        rows: Optional[List[dict[str, Any]]] = None,
        returns_rows: bool = True,
        rowcount: int = 0,
        fail_sql: Optional[str] = None,
    ) -> None:
        self.events = events
        self.rows = rows or []
        self.description = ("column",) if returns_rows else None
        self.rowcount = rowcount
        self.fail_sql = fail_sql
        self._offset = 0
        self.parameters: List[Any] = []

    def execute(self, sql: str, parameters: Any = None) -> None:
        self.events.append(f"execute:{sql}")
        self.parameters.append(parameters)
        if sql == self.fail_sql:
            raise RuntimeError("injected database failure")

    def fetchmany(self, size: int) -> List[dict[str, Any]]:
        self.events.append(f"fetchmany:{size}")
        batch = self.rows[self._offset : self._offset + size]
        self._offset += len(batch)
        return batch

    def close(self) -> None:
        self.events.append("cursor.close")


class FakePostgresConnection:
    def __init__(
        self,
        cursor: FakePostgresCursor,
        events: List[str],
        *,
        fail_rollback: bool = False,
    ) -> None:
        self._cursor = cursor
        self.events = events
        self.fail_rollback = fail_rollback

    def cursor(self, cursor_factory: Any) -> FakePostgresCursor:
        assert cursor_factory == "RealDictCursor"
        self.events.append("cursor")
        return self._cursor

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")
        if self.fail_rollback:
            raise RuntimeError("injected rollback failure")

    def close(self) -> None:
        self.events.append("connection.close")


class FakePsycopg2:
    extras = SimpleNamespace(RealDictCursor="RealDictCursor")

    def __init__(self, connection: FakePostgresConnection, events: List[str]) -> None:
        self.connection = connection
        self.events = events

    def connect(self, *args: Any, **kwargs: Any) -> FakePostgresConnection:
        self.events.append("connect")
        return self.connection


def make_postgres_runner(
    *,
    read_only: bool,
    rows: Optional[List[dict[str, Any]]] = None,
    returns_rows: bool = True,
    rowcount: int = 0,
    fail_sql: Optional[str] = None,
    fail_rollback: bool = False,
    max_result_rows: int = DEFAULT_MAX_RESULT_ROWS,
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
    query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
) -> tuple[PostgresRunner, List[str]]:
    events: List[str] = []
    cursor = FakePostgresCursor(
        events,
        rows=rows,
        returns_rows=returns_rows,
        rowcount=rowcount,
        fail_sql=fail_sql,
    )
    connection = FakePostgresConnection(
        cursor,
        events,
        fail_rollback=fail_rollback,
    )
    runner = PostgresRunner.__new__(PostgresRunner)
    runner.read_only = read_only
    runner.native_read_only = read_only
    runner._read_only_policy = ReadOnlySqlPolicy("postgres")
    runner.connection_string = "postgresql://unused"
    runner.connection_params = None
    runner.psycopg2 = FakePsycopg2(connection, events)
    runner.max_result_rows = max_result_rows
    runner.max_result_bytes = max_result_bytes
    runner.query_timeout_seconds = query_timeout_seconds
    runner.statement_timeout_ms = int(query_timeout_seconds * 1_000)
    return runner, events


@pytest.mark.asyncio
async def test_postgres_read_only_transaction_begins_before_user_sql_and_rolls_back() -> (
    None
):
    runner, events = make_postgres_runner(read_only=True, rows=[{"answer": 42}])

    df = await runner.run_sql(RunSqlToolArgs(sql="SELECT 42 AS answer"), None)

    assert runner.dialect == "postgres"
    assert runner.native_read_only is True
    assert df.to_dict("records") == [{"answer": 42}]
    assert events == [
        "connect",
        "cursor",
        "execute:BEGIN TRANSACTION READ ONLY",
        "execute:SET LOCAL statement_timeout = %s",
        "execute:SELECT 42 AS answer",
        "fetchmany:256",
        "fetchmany:256",
        "cursor.close",
        "rollback",
        "connection.close",
    ]
    assert "commit" not in events


@pytest.mark.asyncio
async def test_postgres_runner_enforces_timeout_and_row_budget() -> None:
    runner, events = make_postgres_runner(
        read_only=True,
        rows=[{"answer": 1}, {"answer": 2}],
        max_result_rows=1,
        query_timeout_seconds=2.5,
    )

    with pytest.raises(SqlResultLimitError, match="row limit"):
        await runner.run_sql(RunSqlToolArgs(sql="SELECT answer FROM answers"), None)

    assert events.index("execute:BEGIN TRANSACTION READ ONLY") < events.index(
        "execute:SET LOCAL statement_timeout = %s"
    )
    assert events.index("execute:SET LOCAL statement_timeout = %s") < events.index(
        "execute:SELECT answer FROM answers"
    )
    cursor = runner.psycopg2.connection._cursor
    assert cursor.parameters[1] == (2500,)
    assert "fetchall" not in events


@pytest.mark.asyncio
async def test_postgres_read_only_runner_rolls_back_on_user_sql_error() -> None:
    sql = "SELECT missing_column FROM users"
    runner, events = make_postgres_runner(read_only=True, fail_sql=sql)

    with pytest.raises(RuntimeError, match="injected database failure"):
        await runner.run_sql(RunSqlToolArgs(sql=sql), None)

    assert events.index("execute:BEGIN TRANSACTION READ ONLY") < events.index(
        f"execute:{sql}"
    )
    assert "rollback" in events
    assert "commit" not in events
    assert events[-1] == "connection.close"


@pytest.mark.asyncio
async def test_postgres_connection_closes_when_rollback_fails() -> None:
    runner, events = make_postgres_runner(
        read_only=True,
        rows=[{"answer": 42}],
        fail_rollback=True,
    )

    with pytest.raises(RuntimeError, match="injected rollback failure"):
        await runner.run_sql(RunSqlToolArgs(sql="SELECT 42 AS answer"), None)

    assert events[-2:] == ["rollback", "connection.close"]


@pytest.mark.asyncio
async def test_postgres_read_only_runner_blocks_write_before_connect() -> None:
    runner, events = make_postgres_runner(read_only=True, returns_rows=False)

    with pytest.raises(SqlPolicyViolation):
        await runner.run_sql(RunSqlToolArgs(sql="DELETE FROM users"), None)

    assert events == []


@pytest.mark.asyncio
async def test_postgres_explicit_writable_mode_preserves_setup_path() -> None:
    runner, events = make_postgres_runner(
        read_only=False, returns_rows=False, rowcount=2
    )

    df = await runner.run_sql(
        RunSqlToolArgs(sql="INSERT INTO users(id) VALUES (1), (2)"), None
    )

    assert runner.native_read_only is False
    assert df.to_dict("records") == [{"rows_affected": 2}]
    assert "execute:BEGIN TRANSACTION READ ONLY" not in events
    assert "commit" in events
    assert "rollback" not in events


def test_legacy_runner_capabilities_have_safe_concrete_defaults() -> None:
    class LegacyRunner(SqlRunner):
        async def run_sql(self, args: RunSqlToolArgs, context: Any) -> Any:
            raise NotImplementedError

    runner = LegacyRunner()
    assert runner.dialect == "unknown"
    assert runner.native_read_only is False


@pytest.mark.parametrize(
    ("runner_type", "dialect"),
    [
        (BigQueryRunner, "bigquery"),
        (ClickHouseRunner, "clickhouse"),
        (DuckDBRunner, "duckdb"),
        (HiveRunner, "hive"),
        (MSSQLRunner, "tsql"),
        (MySQLRunner, "mysql"),
        (OracleRunner, "oracle"),
        (PostgresRunner, "postgres"),
        (PrestoRunner, "presto"),
        (SnowflakeRunner, "snowflake"),
        (SqliteRunner, "sqlite"),
    ],
)
def test_built_in_sql_runners_declare_supported_dialects(
    runner_type: type[SqlRunner], dialect: str
) -> None:
    assert runner_type.dialect == dialect
    ReadOnlySqlPolicy(dialect).validate("SELECT 1")


class FakeDuckDBConnection:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
        *,
        delay_seconds: float = 0,
        block_until_interrupt: bool = False,
    ) -> None:
        self.rows = rows
        self.delay_seconds = delay_seconds
        self.block_until_interrupt = block_until_interrupt
        self.description = [("value",)]
        self.rowcount = -1
        self.events: list[str] = []
        self._offset = 0
        self._interrupted = threading.Event()

    def execute(self, sql: str) -> "FakeDuckDBConnection":
        self.events.append(f"execute:{sql}")
        self._offset = 0
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.block_until_interrupt:
            if not self._interrupted.wait(timeout=2):
                raise RuntimeError("fake query did not receive an interrupt")
            raise RuntimeError("fake driver interrupted")
        return self

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        self.events.append(f"fetchmany:{size}")
        batch = self.rows[self._offset : self._offset + size]
        self._offset += len(batch)
        return batch

    def interrupt(self) -> None:
        self.events.append("interrupt")
        self._interrupted.set()


class FakeDuckDBModule:
    def __init__(self, connection: FakeDuckDBConnection) -> None:
        self.connection = connection
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []

    def connect(self, database_path: str, **kwargs: Any) -> FakeDuckDBConnection:
        self.connect_calls.append((database_path, kwargs))
        return self.connection


def make_duckdb_runner(
    monkeypatch: pytest.MonkeyPatch,
    connection: FakeDuckDBConnection,
    **kwargs: Any,
) -> DuckDBRunner:
    module = FakeDuckDBModule(connection)
    monkeypatch.setitem(sys.modules, "duckdb", module)
    return DuckDBRunner(**kwargs)


@pytest.mark.asyncio
async def test_duckdb_runner_fetches_in_worker_and_never_uses_to_df(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeDuckDBConnection([(1,)], delay_seconds=0.05)
    runner = make_duckdb_runner(monkeypatch, connection)
    task = asyncio.create_task(
        runner.run_sql(RunSqlToolArgs(sql="SELECT 1 AS value"), None)
    )

    await asyncio.sleep(0.01)
    assert task.done() is False
    assert (await task).to_dict("records") == [{"value": 1}]
    assert connection.events == [
        "execute:SELECT 1 AS value",
        "fetchmany:256",
        "fetchmany:256",
    ]


@pytest.mark.asyncio
async def test_duckdb_runner_enforces_row_and_byte_limits_before_dataframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row_connection = FakeDuckDBConnection([(1,), (2,)])
    row_runner = make_duckdb_runner(
        monkeypatch,
        row_connection,
        max_result_rows=1,
    )
    with pytest.raises(SqlResultLimitError, match="row limit"):
        await row_runner.run_sql(RunSqlToolArgs(sql="SELECT value FROM items"), None)

    byte_connection = FakeDuckDBConnection([("materialized-value",)])
    byte_runner = make_duckdb_runner(
        monkeypatch,
        byte_connection,
        max_result_bytes=8,
    )
    with pytest.raises(SqlResultLimitError, match="byte limit"):
        await byte_runner.run_sql(RunSqlToolArgs(sql="SELECT payload"), None)


@pytest.mark.asyncio
async def test_duckdb_runner_interrupts_and_redacts_timeout_driver_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeDuckDBConnection([], block_until_interrupt=True)
    runner = make_duckdb_runner(
        monkeypatch,
        connection,
        query_timeout_seconds=0.01,
    )

    with pytest.raises(SqlQueryTimeoutError, match="configured timeout") as error:
        await runner.run_sql(RunSqlToolArgs(sql="SELECT 1"), None)

    assert "fake driver" not in str(error.value)
    assert connection.events == ["execute:SELECT 1", "interrupt"]
