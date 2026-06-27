import sqlite3
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.integrations.sqlite import SqliteRunner


@pytest.fixture
def seeded_db(tmp_path):
    path = tmp_path / "ro.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    conn.commit()
    conn.close()
    return str(path)


@pytest.mark.asyncio
async def test_read_only_runner_allows_select(seeded_db):
    runner = SqliteRunner(database_path=seeded_db, read_only=True)
    df = await runner.run_sql(RunSqlToolArgs(sql="SELECT * FROM t"), context=None)
    assert len(df) == 1


@pytest.mark.asyncio
async def test_read_only_runner_blocks_direct_write(seeded_db):
    runner = SqliteRunner(database_path=seeded_db, read_only=True)
    with pytest.raises(Exception):
        await runner.run_sql(
            RunSqlToolArgs(sql="INSERT INTO t VALUES (2, 'b')"), context=None
        )
    # confirm the row was NOT inserted
    conn = sqlite3.connect(seeded_db)
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert count == 1
