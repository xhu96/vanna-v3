import sqlite3
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.integrations.semantic import FileSemanticAdapter
from vanna.integrations.sqlite import SqliteRunner


MODEL = """
metrics:
  - name: revenue
    synonyms: ["sales", "income"]
    sql: "SELECT month, SUM(amount) AS revenue FROM sales GROUP BY month"
  - name: orders
    synonyms: ["order count"]
    sql: "SELECT day, COUNT(*) AS orders FROM orders_tbl GROUP BY day"
"""


@pytest.fixture
def model_file(tmp_path):
    p = tmp_path / "model.yaml"
    p.write_text(MODEL)
    return str(p)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (month TEXT, amount INTEGER)")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?)",
        [("2025-01", 100), ("2025-01", 50), ("2025-02", 80)],
    )
    conn.commit()
    conn.close()
    return str(path)


def _adapter(model_file, db):
    runner = SqliteRunner(database_path=db, read_only=True)
    return FileSemanticAdapter(model_path=model_file, sql_runner=runner)


@pytest.mark.asyncio
async def test_plan_full_coverage_on_synonym(model_file, db):
    adapter = _adapter(model_file, db)
    hint = await adapter.plan("show me total sales by month", context=None)
    assert hint.coverage == "full"
    assert hint.request is not None
    assert hint.request.metric == "revenue"


@pytest.mark.asyncio
async def test_plan_missing_coverage(model_file, db):
    adapter = _adapter(model_file, db)
    hint = await adapter.plan("employee attrition by manager", context=None)
    assert hint.coverage == "missing"
    assert hint.request is None


@pytest.mark.asyncio
async def test_execute_runs_real_sql(model_file, db):
    adapter = _adapter(model_file, db)
    from vanna.capabilities.semantic import SemanticQueryRequest

    result = await adapter.execute(SemanticQueryRequest(metric="revenue"), context=None)
    assert result.row_count == 2  # two months
    assert result.metadata["semantic_metric"] == "revenue"


@pytest.mark.asyncio
async def test_execute_unknown_metric_is_empty(model_file, db):
    adapter = _adapter(model_file, db)
    from vanna.capabilities.semantic import SemanticQueryRequest

    result = await adapter.execute(SemanticQueryRequest(metric="nope"), context=None)
    assert result.row_count == 0
