import sqlite3
import pytest

from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.capabilities.semantic import SemanticQueryRequest
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.semantic import FileSemanticAdapter
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.sqlite import SqliteRunner
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy


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
    conn.execute("CREATE TABLE sales (month TEXT, amount INTEGER, tenant_id TEXT)")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?, ?)",
        [
            ("2025-01", 100, "tenant-a"),
            ("2025-01", 50, "tenant-a"),
            ("2025-02", 80, "tenant-a"),
            ("2025-01", 999, "tenant-b"),
        ],
    )
    conn.commit()
    conn.close()
    return str(path)


def _adapter(model_file, db):
    runner = SqliteRunner(database_path=db, read_only=True)
    return FileSemanticAdapter(
        model_path=model_file,
        sql_runner=runner,
        query_policy=SqlQueryPolicy("sqlite", require_row_policies=False),
    )


@pytest.fixture
def tool_context():
    return ToolContext(
        user=User(id="user-a", metadata={"tenant_id": "tenant-a"}),
        conversation_id="conversation-a",
        request_id="request-a",
        agent_memory=DemoAgentMemory(),
    )


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

    result = await adapter.execute(SemanticQueryRequest(metric="revenue"), context=None)
    assert result.row_count == 2  # two months
    assert result.metadata["semantic_metric"] == "revenue"


@pytest.mark.asyncio
async def test_execute_unknown_metric_is_empty(model_file, db):
    adapter = _adapter(model_file, db)

    result = await adapter.execute(SemanticQueryRequest(metric="nope"), context=None)
    assert result.row_count == 0


@pytest.mark.asyncio
async def test_file_semantic_execution_uses_shared_rls_policy(
    model_file, db, tool_context
):
    policy = SqlQueryPolicy(
        "sqlite",
        row_policies=[
            RowFilterPolicy(
                column="tenant_id",
                value="tenant-a",
                tables=frozenset({"sales"}),
            )
        ],
        require_row_policies=True,
    )
    adapter = FileSemanticAdapter(
        model_path=model_file,
        sql_runner=SqliteRunner(database_path=db, read_only=True),
        query_policy=policy,
    )

    result = await adapter.execute(
        SemanticQueryRequest(metric="revenue"), context=tool_context
    )

    assert result.rows == [
        {"month": "2025-01", "revenue": 150},
        {"month": "2025-02", "revenue": 80},
    ]
    assert "tenant_id = 'tenant-a'" in result.metadata["executed_sql"]
    assert result.metadata["validation_checks"] == ["shared_sql_query_policy_passed"]


@pytest.mark.asyncio
async def test_file_semantic_execution_blocks_mutating_metric_sql(
    tmp_path, db, tool_context
):
    model_path = tmp_path / "unsafe-model.yaml"
    model_path.write_text(
        "metrics:\n  - name: erase\n    sql: 'DELETE FROM sales'\n",
        encoding="utf-8",
    )
    adapter = FileSemanticAdapter(
        model_path=str(model_path),
        sql_runner=SqliteRunner(database_path=db, read_only=True),
        query_policy=SqlQueryPolicy("sqlite"),
    )

    with pytest.raises(SqlPolicyViolation):
        await adapter.execute(
            SemanticQueryRequest(metric="erase"), context=tool_context
        )

    connection = sqlite3.connect(db)
    try:
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone() == (4,)
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_default_file_semantic_policy_requires_tenant_rls(
    model_file, db, tool_context
):
    adapter = FileSemanticAdapter(
        model_path=model_file,
        sql_runner=SqliteRunner(database_path=db, read_only=True),
    )

    with pytest.raises(SqlPolicyViolation, match="required tenant policies"):
        await adapter.execute(
            SemanticQueryRequest(metric="revenue"), context=tool_context
        )


@pytest.mark.asyncio
async def test_file_semantic_malformed_context_policy_fails_closed(
    model_file, db, tool_context
):
    adapter = FileSemanticAdapter(
        model_path=model_file,
        sql_runner=SqliteRunner(database_path=db, read_only=True),
    )
    tool_context.metadata["sql_row_policies"] = {"tenant_id": "tenant-a"}

    with pytest.raises(SqlPolicyViolation, match="configured policies are invalid"):
        await adapter.execute(
            SemanticQueryRequest(metric="revenue"), context=tool_context
        )


def test_file_semantic_requires_native_read_only_runner(model_file, db) -> None:
    runner = SqliteRunner(database_path=db, read_only=True)
    runner.native_read_only = False

    with pytest.raises(SqlPolicyViolation, match="native read-only"):
        FileSemanticAdapter(
            model_path=model_file,
            sql_runner=runner,
            query_policy=SqlQueryPolicy("sqlite", require_row_policies=False),
        )

    FileSemanticAdapter(
        model_path=model_file,
        sql_runner=runner,
        query_policy=SqlQueryPolicy("sqlite", require_row_policies=False),
        require_native_read_only=False,
    )
