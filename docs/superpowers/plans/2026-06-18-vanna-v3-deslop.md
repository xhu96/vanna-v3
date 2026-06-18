# vanna-v3 De-Slop & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the AI-slop in vanna-v3 into honest, hardened code — make "secure-by-default" true, build the stubbed features for real, delete the unused legacy subsystem (and its CVEs), and ship it as a reviewable PR.

**Architecture:** Work on branch `cleanup/v3-deslop` in the local clone at `/Users/mac/Documents/Claude/Projects/vanna-v3`. TDD throughout; the full non-integration suite stays green after every task. Order: **C (delete legacy) → A (security) → B (build for real) → D (de-slop) → E (docs/version) → F (deliver)**.

**Tech Stack:** Python 3.14, pytest (`pytest-asyncio`, `asyncio_mode=auto`), pydantic v2, sqlglot (new dep), sqlparse (existing), asgiref (new dep), Flask/FastAPI, ruff + mypy.

**Conventions (match existing code):**
- Run tests from repo root with the venv: `source .venv/bin/activate` then `python -m pytest ...`.
- Async tests use `@pytest.mark.asyncio` (already configured).
- Keep `from __future__ import annotations`, pydantic models, ABC interfaces, and the `Tool`/`SqlRunner`/`SemanticAdapter` injection patterns already in the tree.
- Commit after each task with a conventional-commit message.

**Baseline (verified 2026-06-18):** `python -m pytest -m "not integration"` → green; the 17 v3 tests pass; 274 tests collect.

---

## Phase 0: Setup verification

### Task 0: Confirm green baseline on the branch

**Files:** none (verification only)

- [ ] **Step 1: Confirm branch + env**

Run:
```bash
cd /Users/mac/Documents/Claude/Projects/vanna-v3
git branch --show-current        # expect: cleanup/v3-deslop
source .venv/bin/activate
python -m pytest -m "not integration" -q 2>&1 | tail -5
```
Expected: branch is `cleanup/v3-deslop`; tests pass (record the passed count, call it `BASELINE_N`).

- [ ] **Step 2: Record baseline count** in your working notes. Every later task must keep the suite green (count changes only when a task adds/removes tests, which each task states explicitly).

---

## Phase C: Delete unused legacy cruft (do first — shrinks the surface, removes CVEs)

### Task C1: Delete `src/vanna/legacy/` and all its references

**Files:**
- Delete: `src/vanna/legacy/` (entire directory, ~70 `.py` files)
- Delete: `tests/test_legacy_adapter.py`
- Delete: `tests/test_legacy_chart_security.py`
- Modify: `tests/test_database_sanity.py` (remove 3 legacy test classes)
- Modify: `pyproject.toml` (remove `legacy` marker line)
- Modify: `tests/conftest.py` (remove `legacy` marker registration)
- Modify: `.github/workflows/tests.yml` (remove `tests/test_legacy_chart_security.py` from the pytest invocation)

Background (verified): **no `src/` runtime module imports `vanna.legacy`**; `src/vanna/__init__.py` has **no** legacy re-exports; the active chart path (`visualize_data.py`, `chart_spec`) does **not** import legacy. All references are test/docs/config only. CVE-2026-4513 lives in `legacy/base/base.py`; CVE-2026-4229 in `legacy/google/bigquery_vector.py` — both removed by this deletion.

- [ ] **Step 1: Delete the legacy package and its two dedicated test files**

```bash
cd /Users/mac/Documents/Claude/Projects/vanna-v3
git rm -r --quiet src/vanna/legacy
git rm --quiet tests/test_legacy_adapter.py tests/test_legacy_chart_security.py
```

- [ ] **Step 2: Remove the 3 legacy test classes from `tests/test_database_sanity.py`**

Open `tests/test_database_sanity.py` and delete these three class blocks **in their entirety** (identify by class name; delete the full class body and the surrounding blank lines):
- `class TestLegacySqlRunner` (methods: `test_legacy_sql_runner_import`, `test_legacy_sql_runner_implements_sql_runner`, `test_legacy_sql_runner_has_run_sql_method`, `test_legacy_sql_runner_instantiation`)
- `class TestLegacyVannaBaseConnections` (methods: `test_vanna_base_import`, `test_vanna_base_has_connection_methods`, `test_vanna_base_has_run_sql_method`)
- `class TestLegacyVannaAdapter` (methods: `test_legacy_vanna_adapter_import`, `test_legacy_vanna_adapter_is_tool_registry`)

Keep `TestDatabaseIntegrationModules` and `TestSnowflakeRunner` (not legacy-dependent).

Verify nothing legacy remains in the file:
```bash
grep -n "legacy" tests/test_database_sanity.py    # expect: no output
```

- [ ] **Step 3: Remove the `legacy` pytest marker**

In `pyproject.toml`, delete the line (in the `[tool.pytest.ini_options] markers` list):
```toml
    "legacy: marks tests for legacy adapter",
```
In `tests/conftest.py`, delete the line:
```python
    config.addinivalue_line("markers", "legacy: marks tests for LegacyVannaAdapter")
```

- [ ] **Step 4: Remove the deleted test from CI**

In `.github/workflows/tests.yml`, find the v3 pytest line and remove ` tests/test_legacy_chart_security.py` from it (leave the other test files intact).

- [ ] **Step 5: Verify no dangling references and a green suite**

```bash
grep -rn "vanna.legacy\|from .legacy\|import legacy\|LegacyVannaAdapter\|LegacySqlRunner" src tests --include='*.py'   # expect: no output
python -m pytest -m "not integration" -q 2>&1 | tail -5
```
Expected: no grep output; suite green (count = `BASELINE_N` minus the 12 deleted legacy tests: 2 in test_legacy_adapter + 1 in test_legacy_chart_security + 9 across the 3 removed classes).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove unused legacy subsystem (deletes CVE-2026-4513/4229 code paths)"
```

---

## Phase A: Security correctness

### Task A1: AST-based read-only SQL validation (block CTE-writes & stacked statements)

**Files:**
- Modify: `pyproject.toml` (add `sqlglot` to core `dependencies`)
- Modify: `src/vanna/tools/run_sql.py` (rewrite `_validate_read_only_sql`)
- Test: `tests/test_sql_security.py` (add cases; keep existing 3 green)

- [ ] **Step 1: Add `sqlglot` dependency and install**

In `pyproject.toml` core `dependencies`, add `"sqlglot>=25.0.0",`. Then:
```bash
pip install -q -e '.[test]'
python -c "import sqlglot; print(sqlglot.__version__)"
```

- [ ] **Step 2: Write failing tests** in `tests/test_sql_security.py` (append):

```python
import pytest
from vanna.tools.run_sql import RunSqlTool


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
```

- [ ] **Step 3: Run, verify failure**

Run: `python -m pytest tests/test_sql_security.py -q`
Expected: the new `test_blocks_data_modifying_cte` fails (current first-keyword validator allows `WITH`).

- [ ] **Step 4: Rewrite `_validate_read_only_sql`** in `src/vanna/tools/run_sql.py`.

Add near the top imports:
```python
import sqlglot
from sqlglot import expressions as exp
```
Add a module-level constant (above the class):
```python
# Any of these appearing anywhere in the parsed tree means the statement
# mutates data/schema — including inside CTEs — and must be blocked.
_WRITE_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
)
```
Replace the body of `_validate_read_only_sql`:
```python
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

    first_keyword = sql.strip().split(None, 1)[0].upper()
    if first_keyword not in self.allowed_statement_types:
        allowed_list = ", ".join(sorted(self.allowed_statement_types))
        return (
            f"Blocked by read-only SQL policy. "
            f"Allowed statement types: {allowed_list}."
        )
    return None
```

> Note for the implementer: sqlglot expression class names are stable but version-sensitive. If `import` of any name in `_WRITE_EXPRESSIONS` fails, list available names with `python -c "import sqlglot.expressions as e; print([n for n in dir(e) if n[0].isupper()])"` and adjust (e.g. `Alter` vs `AlterTable`). The tests are the source of truth.

- [ ] **Step 5: Run tests, verify pass**

Run: `python -m pytest tests/test_sql_security.py -q`
Expected: all pass (the original 3 + the 5 new).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/vanna/tools/run_sql.py tests/test_sql_security.py
git commit -m "fix(security): AST-based read-only SQL validation blocks CTE-writes and stacked statements"
```

### Task A2: Enforce read-only at the connection layer + fix PRAGMA injection in schema_sync

**Files:**
- Modify: `src/vanna/integrations/sqlite/sql_runner.py` (add `read_only`, open URI read-only)
- Modify: `src/vanna/integrations/postgres/sql_runner.py` (add `read_only`, `SET TRANSACTION READ ONLY`)
- Modify: `src/vanna/services/schema_sync.py` (validate `table_name` before the PRAGMA f-string)
- Test: `tests/test_sql_runner_read_only.py` (new)

- [ ] **Step 1: Write failing tests** — create `tests/test_sql_runner_read_only.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_sql_runner_read_only.py -q`
Expected: fails — `SqliteRunner.__init__` has no `read_only` parameter.

- [ ] **Step 3: Implement read-only in `SqliteRunner`** (`src/vanna/integrations/sqlite/sql_runner.py`).

Add `read_only: bool = True` to `__init__` and store `self.read_only`. In `run_sql`, replace the connect line and gate writes:
```python
if self.read_only:
    # Open the database read-only at the driver level (defense in depth).
    conn = sqlite3.connect(
        f"file:{self.database_path}?mode=ro", uri=True
    )
else:
    conn = sqlite3.connect(self.database_path)
```
A read-only SQLite connection raises `sqlite3.OperationalError` on any write, so no extra guard is needed; the existing `finally: conn.close()` stays. (The non-SELECT `commit()` branch will now only run when `read_only=False`.)

- [ ] **Step 4: Implement read-only in `PostgresRunner`** (`src/vanna/integrations/postgres/sql_runner.py`).

Add `read_only: bool = True` to `__init__` and store it. In `run_sql`, immediately after creating the cursor and before `cursor.execute(args.sql)`:
```python
if self.read_only:
    # Enforce read-only at the transaction level so direct-runner paths
    # (e.g. schema_sync) cannot mutate data even if they bypass RunSqlTool.
    cursor.execute("SET TRANSACTION READ ONLY")
```
Postgres then raises on any write within the transaction. Keep the rest as-is (the non-SELECT `commit()` branch only matters when `read_only=False`).

- [ ] **Step 5: Fix the PRAGMA injection in `schema_sync.py`**

In `src/vanna/services/schema_sync.py`, the line `RunSqlToolArgs(sql=f"PRAGMA table_info('{table_name}')")` interpolates `table_name`. PRAGMA arguments cannot be parameterized, so validate the identifier first. Add near the top:
```python
import re

_SQLITE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
```
Replace the PRAGMA call with a guarded version:
```python
if not _SQLITE_IDENT.match(table_name):
    raise ValueError(f"Refusing unsafe table identifier: {table_name!r}")
pragma_df = await self.sql_runner.run_sql(
    RunSqlToolArgs(sql=f'PRAGMA table_info("{table_name}")'),
    context,
)
```

- [ ] **Step 6: Run all affected tests, verify pass**

Run:
```bash
python -m pytest tests/test_sql_runner_read_only.py tests/test_schema_diff.py -q
```
Expected: pass. (If `test_schema_diff.py` constructs a `SqliteRunner` against a temp DB it writes to, ensure the test that *populates* the DB uses a normal connection, not the read-only runner — the runner is for queries only.)

- [ ] **Step 7: Commit**

```bash
git add src/vanna/integrations/sqlite/sql_runner.py src/vanna/integrations/postgres/sql_runner.py src/vanna/services/schema_sync.py tests/test_sql_runner_read_only.py
git commit -m "fix(security): enforce read-only at the connection layer; guard PRAGMA identifier in schema_sync"
```

### Task A3: Safe row-level-security filter helper + rewrite the RLS example

**Files:**
- Create: `src/vanna/security/__init__.py`
- Create: `src/vanna/security/rls.py`
- Modify: `examples/v3/multi_tenant_rls.py` (use the helper, drop the f-string)
- Test: `tests/test_rls_filter.py` (new)

- [ ] **Step 1: Write failing tests** — create `tests/test_rls_filter.py`:

```python
import sqlglot
from vanna.security.rls import apply_row_filter


def test_adds_where_when_absent():
    out = apply_row_filter("SELECT * FROM orders", "tenant_id", "tenant-a")
    parsed = sqlglot.parse_one(out)
    assert parsed.find(sqlglot.exp.Where) is not None
    assert "tenant-a" in out


def test_appends_to_existing_where():
    out = apply_row_filter(
        "SELECT * FROM orders WHERE amount > 100", "tenant_id", "tenant-a"
    )
    # both predicates survive
    assert "amount" in out and "tenant_id" in out


def test_injection_is_escaped_not_executed():
    malicious = "x' OR '1'='1"
    out = apply_row_filter("SELECT * FROM orders", "tenant_id", malicious)
    # the value must appear as a single escaped string literal, not break out
    parsed = sqlglot.parse_one(out)
    literals = [n.this for n in parsed.find_all(sqlglot.exp.Literal) if n.is_string]
    assert malicious in literals
    # exactly one WHERE, no OR injected at the top level
    assert out.upper().count(" OR ") == 0


def test_applies_with_group_by():
    out = apply_row_filter(
        "SELECT region, SUM(amount) FROM orders GROUP BY region",
        "tenant_id",
        "tenant-a",
    )
    parsed = sqlglot.parse_one(out)
    assert parsed.find(sqlglot.exp.Where) is not None
    assert parsed.find(sqlglot.exp.Group) is not None
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_rls_filter.py -q`
Expected: fails — module `vanna.security.rls` does not exist.

- [ ] **Step 3: Implement the helper** — create `src/vanna/security/__init__.py` (empty) and `src/vanna/security/rls.py`:

```python
"""Safe, AST-based row-level-security predicate injection."""

from __future__ import annotations

from sqlglot import condition, exp, parse_one


def apply_row_filter(sql: str, column: str, value: str) -> str:
    """Return ``sql`` with ``column = value`` AND-ed into its WHERE clause.

    The value is bound as a properly-escaped string literal via sqlglot, so
    untrusted ``value`` (e.g. a tenant id) cannot break out of the literal.
    The predicate is applied at the AST level, so it composes correctly with
    GROUP BY, HAVING, sub-queries, and existing WHERE clauses.
    """
    if not column.isidentifier():
        raise ValueError(f"Unsafe filter column: {column!r}")

    tree = parse_one(sql)
    predicate = condition(exp.column(column).eq(exp.Literal.string(value)))
    # ``where`` AND-combines with any existing WHERE on a Select.
    tree = tree.where(predicate)
    return tree.sql()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_rls_filter.py -q`
Expected: all pass. (If `tree.where(...)` is unavailable on the parsed node type in the installed sqlglot, use `parse_one(sql).where(predicate)` only for `exp.Select`; the tests cover Select queries.)

- [ ] **Step 5: Rewrite the example** — replace the `transform_args` body in `examples/v3/multi_tenant_rls.py`:

```python
    async def transform_args(
        self,
        tool: Tool,
        args: RunSqlToolArgs,
        user: User,
        context: ToolContext,
    ) -> Union[RunSqlToolArgs, ToolRejection]:
        if tool.name != "run_sql":
            return args

        tenant_id = user.metadata.get("tenant_id")
        if tenant_id is None:
            return ToolRejection(reason="Missing tenant context.")

        safe_sql = apply_row_filter(args.sql, "tenant_id", str(tenant_id))
        return RunSqlToolArgs(sql=safe_sql)
```
And add the import at the top: `from vanna.security.rls import apply_row_filter`. Remove the now-unused manual string handling.

- [ ] **Step 6: Run the suite, verify pass; commit**

```bash
python -m pytest tests/test_rls_filter.py -q
git add src/vanna/security/ examples/v3/multi_tenant_rls.py tests/test_rls_filter.py
git commit -m "fix(security): AST-based RLS filter helper; remove SQL injection in multi_tenant_rls example"
```

### Task A4: Fix result handling for non-SELECT read-only queries (remove the misleading write branch)

**Files:**
- Modify: `src/vanna/tools/run_sql.py` (`execute`)
- Test: `tests/test_sql_security.py` (add a case)

Problem: `query_type = sql.strip().upper().split()[0]` only treats `SELECT` as result-returning, so a legitimate read-only `WITH … SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, or `PRAGMA` falls into the `else` branch and is wrongly reported as "N row(s) affected". Under read-only defaults, the write branch is also dead.

- [ ] **Step 1: Write failing test** in `tests/test_sql_security.py` (append):

```python
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
```

Add a helper at the top of the test module if one is not already present (the tool needs a `ToolContext` to write the CSV via the file system):
```python
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory


def _make_tool_context():
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
    )
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_sql_security.py::test_cte_select_returns_rows_not_rows_affected -q`
Expected: fails — current code reports "row(s) affected" / `query_type == "WITH"` goes to the write branch.

- [ ] **Step 3: Restructure `execute`** so result handling is driven by whether the runner returned rows, not the first keyword. Replace the `if query_type == "SELECT": … else: …` block with:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_sql_security.py tests/test_visualization_tool.py -q`
Expected: pass (the new test + existing).

- [ ] **Step 5: Commit**

```bash
git add src/vanna/tools/run_sql.py tests/test_sql_security.py
git commit -m "fix: return result sets for non-SELECT read-only queries (WITH/SHOW/EXPLAIN) instead of 'rows affected'"
```

---

## Phase B: Build the stubs for real

### Task B1: Real `FileSemanticAdapter` (replace the mock-as-feature)

**Files:**
- Create: `src/vanna/integrations/semantic/file_adapter.py`
- Create: `examples/v3/semantic_model.yaml` (sample model)
- Modify: `src/vanna/integrations/semantic/__init__.py` (export `FileSemanticAdapter`)
- Create: `tests/support/__init__.py` + `tests/support/semantic_fixtures.py` (move the mock here as a test fixture)
- Modify: `tests/test_semantic_planner.py` (import the mock from the fixture)
- Modify: `examples/v3/semantic_adapter_demo.py` (use `FileSemanticAdapter`)
- Test: `tests/test_file_semantic_adapter.py` (new)

Design: a `FileSemanticAdapter` loads a YAML semantic model (metrics with synonyms + a SQL template) and runs queries through an injected `SqlRunner`. `plan()` matches the message against metric names/synonyms (coverage `full` on a metric hit, `missing` otherwise); `execute()` renders the metric's SQL with the requested dimensions/limit and runs it. Uses the exact model fields from `capabilities/semantic/models.py`: `SemanticPlanHint(coverage, reason, request)`, `SemanticQueryRequest(metric, dimensions, filters, time_grain, limit, order_by)`, `SemanticQueryResult(rows, row_count, metadata)`, and `SemanticCoverage = Literal["full","partial","missing"]`.

- [ ] **Step 1: Write failing tests** — create `tests/test_file_semantic_adapter.py`:

```python
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
    conn.executemany("INSERT INTO sales VALUES (?, ?)", [("2025-01", 100), ("2025-01", 50), ("2025-02", 80)])
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_file_semantic_adapter.py -q`
Expected: fails — `FileSemanticAdapter` does not exist.

- [ ] **Step 3: Implement** — create `src/vanna/integrations/semantic/file_adapter.py`:

```python
"""File-backed semantic adapter: a real, self-contained semantic layer.

Metrics are declared in a YAML file (name, synonyms, and a read-only SQL
statement). ``plan`` matches a natural-language message to a metric by
name/synonym; ``execute`` runs the metric's SQL through an injected
``SqlRunner`` and returns the rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from vanna.capabilities.semantic import (
    SemanticAdapter,
    SemanticPlanHint,
    SemanticQueryRequest,
    SemanticQueryResult,
)
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext


class _Metric:
    def __init__(self, name: str, sql: str, synonyms: List[str]):
        self.name = name
        self.sql = sql
        self.synonyms = synonyms


class FileSemanticAdapter(SemanticAdapter):
    """Semantic adapter backed by a YAML metric model and a SqlRunner."""

    def __init__(self, model_path: str, sql_runner: SqlRunner):
        self.model_path = model_path
        self.sql_runner = sql_runner
        self._metrics: Dict[str, _Metric] = self._load_model(model_path)

    @staticmethod
    def _load_model(path: str) -> Dict[str, "_Metric"]:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        metrics: Dict[str, _Metric] = {}
        for entry in data.get("metrics", []):
            name = entry["name"]
            metrics[name] = _Metric(
                name=name,
                sql=entry["sql"],
                synonyms=[s.lower() for s in entry.get("synonyms", [])],
            )
        return metrics

    def _match(self, message: str) -> Optional[_Metric]:
        lowered = message.lower()
        for metric in self._metrics.values():
            terms = [metric.name.lower(), *metric.synonyms]
            if any(term in lowered for term in terms):
                return metric
        return None

    async def plan(self, message: str, context: ToolContext) -> SemanticPlanHint:
        metric = self._match(message)
        if metric is None:
            return SemanticPlanHint(
                coverage="missing",
                reason="No semantic metric matched; fall back to SQL generation.",
                request=None,
            )
        return SemanticPlanHint(
            coverage="full",
            reason=f"Matched semantic metric '{metric.name}'.",
            request=SemanticQueryRequest(metric=metric.name),
        )

    async def execute(
        self, request: SemanticQueryRequest, context: ToolContext
    ) -> SemanticQueryResult:
        metric = self._metrics.get(request.metric)
        if metric is None:
            return SemanticQueryResult(
                rows=[],
                row_count=0,
                metadata={"semantic_metric": request.metric, "matched": False},
            )

        df = await self.sql_runner.run_sql(RunSqlToolArgs(sql=metric.sql), context)
        rows: List[Dict[str, Any]] = df.to_dict("records") if not df.empty else []
        if request.limit:
            rows = rows[: request.limit]
        return SemanticQueryResult(
            rows=rows,
            row_count=len(rows),
            metadata={
                "semantic_metric": metric.name,
                "matched": True,
                "source": "file_semantic_adapter",
                "executed_sql": metric.sql,
            },
        )
```

- [ ] **Step 4: Export it** — in `src/vanna/integrations/semantic/__init__.py`:

```python
from .file_adapter import FileSemanticAdapter
from .mock_adapter import MockSemanticAdapter  # retained for back-compat; demo/test only

__all__ = ["FileSemanticAdapter", "MockSemanticAdapter"]
```
Add a module docstring noting `FileSemanticAdapter` is the production adapter and `MockSemanticAdapter` is a deterministic in-memory fixture for tests/demos.

- [ ] **Step 5: Move the mock to a test fixture** — create `tests/support/__init__.py` (empty) and `tests/support/semantic_fixtures.py` containing a copy of `MockSemanticAdapter` (verbatim from `src/vanna/integrations/semantic/mock_adapter.py`). Update `tests/test_semantic_planner.py` to import it from the fixture:
```python
from tests.support.semantic_fixtures import MockSemanticAdapter
```
(Leave `mock_adapter.py` in place and still exported for back-compat, but tests now depend on the fixture so the mock is no longer load-bearing for the suite.)

- [ ] **Step 6: Add the sample model + update the demo** — create `examples/v3/semantic_model.yaml`:
```yaml
metrics:
  - name: revenue
    synonyms: ["sales", "income"]
    sql: "SELECT month, SUM(amount) AS revenue FROM sales GROUP BY month ORDER BY month"
  - name: orders
    synonyms: ["order count", "orders placed"]
    sql: "SELECT day, COUNT(*) AS orders FROM orders_tbl GROUP BY day ORDER BY day"
```
Rewrite `examples/v3/semantic_adapter_demo.py` to build a `FileSemanticAdapter(model_path="examples/v3/semantic_model.yaml", sql_runner=SqliteRunner(...))` instead of `MockSemanticAdapter`. Keep the file runnable as documentation.

- [ ] **Step 7: Run tests, verify pass**

Run: `python -m pytest tests/test_file_semantic_adapter.py tests/test_semantic_planner.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/vanna/integrations/semantic/ examples/v3/semantic_model.yaml examples/v3/semantic_adapter_demo.py tests/support/ tests/test_file_semantic_adapter.py tests/test_semantic_planner.py
git commit -m "feat(semantic): real FileSemanticAdapter; demote mock to a test fixture"
```

### Task B2: Real offline eval gate (replace hardcoded CI numbers)

**Files:**
- Create: `src/vanna/integrations/mock/scripted_llm.py` (`ScriptedLlmService`)
- Create: `src/evals/datasets/sql_generation/offline_smoke.yaml` (small dataset matching real outputs)
- Create: `src/evals/pipelines/run_offline_eval.py` (runs the agent → writes candidate metrics)
- Create: `src/evals/baselines/sql_generation.json` (committed baseline)
- Modify: `.github/workflows/tests.yml` (run the real eval; delete the hardcoded heredocs)
- Test: `tests/test_offline_eval.py` (new)

Design: a deterministic `ScriptedLlmService` returns a canned, SQL-bearing answer per message so the **real** `Agent` + `EvaluationRunner` + `OutputEvaluator`/`EfficiencyEvaluator` execute end-to-end and produce reproducible `pass_rate`/`average_score`. `run_offline_eval.py` mirrors the existing `src/evals/benchmarks/llm_comparison.py` construction (its `AgentVariant` / `EvaluationRunner` / `compare_agents` usage) but injects the scripted LLM and writes the candidate metrics JSON. The gate compares against a committed baseline. This is an honest **offline regression gate** (deterministic; catches regressions in the agent/evaluator/tooling pipeline) — not a model-quality benchmark. A real-LLM mode remains possible by injecting a real `LlmService`.

- [ ] **Step 1: Read the existing eval construction** to mirror it exactly:

Run:
```bash
sed -n '1,80p' src/evals/benchmarks/llm_comparison.py
sed -n '1,60p' src/vanna/core/evaluation/runner.py
```
Note the exact `AgentVariant(...)`, `EvaluationRunner(...)`, and `compare_agents(...)` call shapes and how `ComparisonReport.reports[name].pass_rate()/average_score()` are read. Use these verbatim in Step 4.

- [ ] **Step 2: Write the scripted LLM and a failing test** — create `tests/test_offline_eval.py`:

```python
import json
import pytest

from vanna.integrations.mock.scripted_llm import ScriptedLlmService


@pytest.mark.asyncio
async def test_scripted_llm_returns_mapped_answer():
    llm = ScriptedLlmService(
        responses={"total sales by region": "SELECT region, SUM(amount) FROM sales GROUP BY region"},
        default="SELECT 1",
    )
    from vanna.core import LlmRequest, LlmMessage

    req = LlmRequest(messages=[LlmMessage(role="user", content="show me total sales by region")])
    resp = await llm.send_request(req)
    assert "SELECT" in resp.content and "region" in resp.content


def test_offline_eval_runner_importable():
    # the pipeline module must import without side effects
    import src.evals.pipelines.run_offline_eval as m  # noqa: F401
    assert hasattr(m, "run_offline_eval")
```

> Implementer note: confirm the exact `LlmRequest`/`LlmMessage` constructor fields via `python -c "from vanna.core import LlmRequest, LlmMessage; print(LlmRequest.model_fields, LlmMessage.model_fields)"` and adjust the test/импl to match (the codebase already defines these; mirror `MockLlmService`'s usage in `src/vanna/integrations/mock/llm.py`).

- [ ] **Step 3: Run, verify failure**

Run: `python -m pytest tests/test_offline_eval.py -q`
Expected: fails — `ScriptedLlmService` / `run_offline_eval` do not exist.

- [ ] **Step 4: Implement `ScriptedLlmService`** — create `src/vanna/integrations/mock/scripted_llm.py`, mirroring the `LlmService` interface used by `MockLlmService` (`send_request` → `LlmResponse(content, finish_reason, usage)`, `stream_request` → `LlmStreamChunk`):

```python
"""Deterministic, scripted LLM for reproducible offline evaluation."""

from __future__ import annotations

from typing import AsyncGenerator, Dict

from vanna.core import LlmRequest, LlmResponse, LlmStreamChunk
from vanna.core.interfaces import LlmService  # mirror MockLlmService's base import


class ScriptedLlmService(LlmService):
    """Return a canned answer chosen by substring-matching the last user message.

    Deterministic: no network, no randomness. Used to drive the real Agent and
    evaluators over a fixed dataset so the eval gate measures real (reproducible)
    pipeline behavior rather than hardcoded numbers.
    """

    def __init__(self, responses: Dict[str, str], default: str = "SELECT 1"):
        self.responses = {k.lower(): v for k, v in responses.items()}
        self.default = default
        self.call_count = 0

    def _answer_for(self, request: LlmRequest) -> str:
        text = ""
        for msg in request.messages:
            if getattr(msg, "role", None) == "user":
                text = (msg.content or "").lower()
        for key, value in self.responses.items():
            if key in text:
                return value
        return self.default

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.call_count += 1
        return LlmResponse(
            content=self._answer_for(request),
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        yield LlmStreamChunk(content=self._answer_for(request), finish_reason="stop")
```

> Implementer note: match the exact base class + import path used by `MockLlmService` (read `src/vanna/integrations/mock/llm.py` line ~15 for `class MockLlmService(...)`). Use the identical base so this is a drop-in.

- [ ] **Step 5: Add the dataset** — create `src/evals/datasets/sql_generation/offline_smoke.yaml` with 3 cases whose `expected_outcome.final_answer_contains` matches the scripted answers (use the **real** tool names where trajectory is checked, but prefer output checks here):

```yaml
dataset:
  name: "SQL Generation - Offline Smoke"
  description: "Deterministic offline smoke eval driven by ScriptedLlmService"
  test_cases:
    - id: "smoke_001"
      user_id: "eval_user"
      username: "evaluator"
      email: "eval@example.com"
      user_groups: ["user", "analyst"]
      message: "Show me total sales by region"
      expected_outcome:
        final_answer_contains: ["SELECT", "region"]
        final_answer_not_contains: ["DROP", "DELETE"]
    - id: "smoke_002"
      user_id: "eval_user"
      username: "evaluator"
      email: "eval@example.com"
      user_groups: ["user", "analyst"]
      message: "What is revenue by month?"
      expected_outcome:
        final_answer_contains: ["SELECT", "month"]
    - id: "smoke_003"
      user_id: "eval_user"
      username: "evaluator"
      email: "eval@example.com"
      user_groups: ["user", "analyst"]
      message: "Count of orders per day"
      expected_outcome:
        final_answer_contains: ["SELECT", "COUNT"]
```

- [ ] **Step 6: Implement the runner** — create `src/evals/pipelines/run_offline_eval.py` that mirrors `llm_comparison.py`'s construction (Step 1), but builds one `AgentVariant` whose agent uses `ScriptedLlmService` (responses keyed to the three messages above), runs `EvaluationRunner(evaluators=[OutputEvaluator(), EfficiencyEvaluator()])` over the dataset, computes `pass_rate`/`average_score` from the resulting report, and writes them to a JSON path:

```python
"""Run the deterministic offline eval and emit candidate metrics JSON."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

# Mirror the imports/construction used by src/evals/benchmarks/llm_comparison.py
from vanna.core import EvaluationDataset, EvaluationRunner, AgentVariant, OutputEvaluator, EfficiencyEvaluator
from vanna.integrations.mock.scripted_llm import ScriptedLlmService
# ... plus whatever llm_comparison.py uses to build a runnable Agent (ToolRegistry, user resolver, etc.)

SCRIPTED = {
    "total sales by region": "SELECT region, SUM(amount) AS total FROM sales GROUP BY region",
    "revenue by month": "SELECT month, SUM(amount) AS revenue FROM sales GROUP BY month",
    "orders per day": "SELECT day, COUNT(*) AS orders FROM orders_tbl GROUP BY day",
}


def build_variant() -> AgentVariant:
    # Construct exactly as llm_comparison.py does, but inject ScriptedLlmService(SCRIPTED).
    ...  # filled in per Step 1 findings


async def run_offline_eval(dataset_path: str) -> dict:
    dataset = EvaluationDataset.from_yaml(dataset_path)
    runner = EvaluationRunner(evaluators=[OutputEvaluator(), EfficiencyEvaluator()], max_concurrency=2)
    report = await runner.compare_agents([build_variant()], dataset.test_cases)
    variant_report = report.reports[build_variant().name] if False else list(report.reports.values())[0]
    return {
        "pass_rate": variant_report.pass_rate(),
        "average_score": variant_report.average_score(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="src/evals/datasets/sql_generation/offline_smoke.yaml")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    metrics = asyncio.run(run_offline_eval(args.dataset))
    args.out.write_text(json.dumps(metrics), encoding="utf-8")
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> Implementer note: the `build_variant()` body and the exact evaluator/runner imports must come from Step 1's reading of `llm_comparison.py` and `runner.py`. Do not invent class shapes; reuse the existing ones. If `OutputEvaluator`/`EfficiencyEvaluator` are not importable from `vanna.core`, import them from their defining module (the same one `llm_comparison.py` uses).

- [ ] **Step 7: Generate and commit the baseline** — once the runner works, produce the baseline from the current (good) state:

```bash
mkdir -p src/evals/baselines
python src/evals/pipelines/run_offline_eval.py --out src/evals/baselines/sql_generation.json
cat src/evals/baselines/sql_generation.json   # expect real, non-trivial pass_rate/average_score
```
The scripted answers satisfy the dataset, so `pass_rate` should be `1.0`. Commit this file as the baseline.

- [ ] **Step 8: Rewire CI** — in `.github/workflows/tests.yml`, replace the "Eval regression gate sample" step (the two hardcoded heredocs + gate call) with a real run:

```yaml
      - name: Offline eval regression gate
        run: |
          python src/evals/pipelines/run_offline_eval.py --out candidate.json
          python src/evals/pipelines/offline_training_gate.py \
            --baseline src/evals/baselines/sql_generation.json \
            --candidate candidate.json \
            --min-score-delta 0.0
```

- [ ] **Step 9: Run tests + a local gate dry-run, verify pass**

```bash
python -m pytest tests/test_offline_eval.py -q
python src/evals/pipelines/run_offline_eval.py --out /tmp/cand.json
python src/evals/pipelines/offline_training_gate.py --baseline src/evals/baselines/sql_generation.json --candidate /tmp/cand.json
echo "gate exit: $?"   # expect 0
```

- [ ] **Step 10: Commit**

```bash
git add src/vanna/integrations/mock/scripted_llm.py src/evals/ .github/workflows/tests.yml tests/test_offline_eval.py
git commit -m "feat(evals): real deterministic offline eval gate; remove hardcoded CI metrics"
```

### Task B3: Weight-aware memory retrieval (make feedback corrections actually rank)

**Files:**
- Modify: `src/vanna/integrations/local/agent_memory/in_memory.py` (`search_similar_usage` ranking)
- Test: `tests/test_feedback_memory_patching.py` (add a ranking test) or new `tests/test_memory_weighting.py`

Design: `feedback.py` writes corrective memories with `metadata={"weight": 5.0, ...}` (and negative ones with `success=False`, already filtered out by the `if m.success` candidate filter). Today ranking sorts by `similarity_score` only, ignoring `weight`. Change ranking to sort by an *effective* score = `similarity_score * weight` (weight defaults to `1.0` when absent), while keeping the `similarity_threshold` filter on the raw similarity and reporting the raw `similarity_score` in the result for transparency.

- [ ] **Step 1: Write failing test** — create `tests/test_memory_weighting.py`:

```python
import pytest

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory


def _ctx(mem):
    return ToolContext(user=User(id="u1", group_memberships=["user"]), conversation_id="c1", request_id="r1", agent_memory=mem)


@pytest.mark.asyncio
async def test_corrective_memory_outranks_plain_memory():
    mem = DemoAgentMemory()
    ctx = _ctx(mem)
    # an ordinary saved usage (default weight)
    await mem.save_tool_usage(
        question="show revenue by month", tool_name="run_sql",
        args={"sql": "SELECT bad"}, context=ctx, success=True,
    )
    # a corrective, high-weight memory for a slightly less identical question
    await mem.save_tool_usage(
        question="show monthly revenue", tool_name="run_sql",
        args={"sql": "SELECT good"}, context=ctx, success=True,
        metadata={"patch_type": "corrective", "weight": 5.0},
    )
    results = await mem.search_similar_usage("show revenue by month", ctx, similarity_threshold=0.1)
    assert results, "expected at least one match"
    assert results[0].memory.args["sql"] == "SELECT good"
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_memory_weighting.py -q`
Expected: fails — the plain (more textually-similar) memory currently ranks first.

- [ ] **Step 3: Implement weighting** — in `src/vanna/integrations/local/agent_memory/in_memory.py`, update `search_similar_usage`’s scoring/sort block:

```python
        # Score each candidate by question similarity, then weight by feedback.
        results: List[tuple[ToolMemory, float, float]] = []
        for m in candidates:
            similarity = min(self._similarity(q, m.question), 1.0)
            weight = 1.0
            if m.metadata and isinstance(m.metadata.get("weight"), (int, float)):
                weight = float(m.metadata["weight"])
            effective = similarity * weight
            results.append((m, similarity, effective))

        # Filter on raw similarity, rank by effective (similarity * weight).
        results = [r for r in results if r[1] >= similarity_threshold]
        results.sort(key=lambda x: x[2], reverse=True)

        out: List[ToolMemorySearchResult] = []
        for idx, (m, similarity, _effective) in enumerate(results[:limit], start=1):
            out.append(
                ToolMemorySearchResult(memory=m, similarity_score=similarity, rank=idx)
            )
        return out
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_memory_weighting.py tests/test_feedback_memory_patching.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/vanna/integrations/local/agent_memory/in_memory.py tests/test_memory_weighting.py
git commit -m "feat(memory): weight-aware retrieval so feedback corrections actually re-rank results"
```

---

## Phase D: De-slop & consistency

### Task D1: Replace per-request event loops in Flask routes

**Files:**
- Modify: `pyproject.toml` (add `asgiref>=3.7` to the `flask` and `fastapi` extras)
- Create: `src/vanna/servers/flask/_async.py` (sync bridge helpers)
- Modify: `src/vanna/servers/flask/routes.py` (replace ~9 `new_event_loop` sites)
- Test: `tests/test_flask_async_bridge.py` (new)

- [ ] **Step 1: Add dependency**

In `pyproject.toml`, add `"asgiref>=3.7"` to the `flask` and `fastapi` optional-dependency lists. Then `pip install -q -e '.[flask,fastapi,test]'`.

- [ ] **Step 2: Write failing test** — create `tests/test_flask_async_bridge.py`:

```python
import pytest
from vanna.servers.flask._async import run_async, iter_async


def test_run_async_executes_coroutine():
    async def coro():
        return 42
    assert run_async(coro()) == 42


def test_iter_async_collects_generator():
    async def agen():
        for i in range(3):
            yield i
    assert list(iter_async(agen())) == [0, 1, 2]
```

- [ ] **Step 3: Run, verify failure**

Run: `python -m pytest tests/test_flask_async_bridge.py -q`
Expected: fails — module doesn't exist.

- [ ] **Step 4: Implement the bridge** — create `src/vanna/servers/flask/_async.py`:

```python
"""Sync bridges for running async agent code from Flask's WSGI threads.

Uses a single dedicated event loop running in a background thread, avoiding
the fragile per-request ``asyncio.new_event_loop()`` pattern.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncGenerator, Coroutine, Generator, Iterator, TypeVar

_T = TypeVar("_T")

_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, name="vanna-async", daemon=True)
_thread.start()


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine to completion on the shared background loop."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


def iter_async(agen: AsyncGenerator[_T, None]) -> Iterator[_T]:
    """Iterate an async generator synchronously via the shared loop."""
    while True:
        try:
            yield asyncio.run_coroutine_threadsafe(agen.__anext__(), _loop).result()
        except StopAsyncIteration:
            return
```

- [ ] **Step 5: Replace the loop sites in `routes.py`**

Add `from ._async import run_async, iter_async` at the top of `src/vanna/servers/flask/routes.py`. Then replace each `loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); try: … loop.run_until_complete(X) … finally: loop.close()` block with `run_async(X)`. For the streaming `generate()` functions (`chat_sse`, `chat_events_v3`), replace the manual `loop.run_until_complete(gen.__anext__())` loop with:
```python
def generate() -> Generator[str, None, None]:
    for chunk in iter_async(async_generate()):
        yield chunk
    yield "data: [DONE]\n\n"
```
(adapting `async_generate()` to remain an `async def` that yields the formatted SSE strings). Remove the now-unused `asyncio` import if nothing else uses it.

- [ ] **Step 6: Run the suite, verify pass**

Run: `python -m pytest tests/test_flask_async_bridge.py -m "not integration" -q 2>&1 | tail -5`
Expected: bridge tests pass; full suite still green. (If any Flask route test exists, it must still pass.)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/vanna/servers/flask/_async.py src/vanna/servers/flask/routes.py tests/test_flask_async_bridge.py
git commit -m "refactor(flask): replace per-request event loops with a shared async bridge"
```

### Task D2: Remove genuinely-unused interface (only if zero implementers)

**Files:** (conditional) `src/vanna/capabilities/schema_catalog/` and its `core/__init__` export

- [ ] **Step 1: Check for implementers**

Run:
```bash
grep -rn "SchemaCatalog)" src --include='*.py'
grep -rn "SchemaCatalog" src tests --include='*.py'
```

- [ ] **Step 2: Decide and act**
  - If `SchemaCatalog` has **at least one** concrete implementer or is referenced by `schema_sync`/servers → **leave it** (it's a real pluggability seam; do nothing, mark this task done with a note).
  - If it has **zero** implementers and is imported nowhere meaningful → remove the `schema_catalog` capability package and its export from `src/vanna/core/__init__.py` (and any `__all__` entry). Run `python -c "import vanna"` to confirm no import breaks.

- [ ] **Step 3: Run suite + commit (only if a change was made)**

```bash
python -m pytest -m "not integration" -q 2>&1 | tail -3
git add -A && git commit -m "refactor: remove unused schema_catalog interface (zero implementers)"
```
If no change was made, skip the commit and record the rationale in the PR description.

### Task D3: Make confidence scoring honest (no false precision)

**Files:**
- Modify: `src/vanna/core/lineage/confidence.py`
- Modify: wherever the lineage card is built (the agent emits an "Evidence and Lineage" card) to surface the contributing signals
- Test: `tests/test_lineage_capture.py` (extend)

- [ ] **Step 1: Write failing test** in `tests/test_lineage_capture.py` (append a case) asserting the confidence result exposes its reasoning, e.g. the tier plus the boolean signals it was based on:

```python
def test_confidence_exposes_signals():
    from vanna.core.lineage.confidence import ConfidenceScorer
    from vanna.core.lineage.models import LineageEvidence

    evidence = LineageEvidence()  # empty → "Low"
    detail = ConfidenceScorer.explain(evidence)
    assert detail["tier"] == "Low"
    assert set(detail["signals"]) >= {"has_sql", "has_semantic", "has_validation", "has_errors"}
```

- [ ] **Step 2: Run, verify failure** — `ConfidenceScorer.explain` doesn't exist.

- [ ] **Step 3: Implement** — in `confidence.py`, add an `explain` classmethod that returns the tier plus the signals, and have `score` delegate to it:

```python
    @staticmethod
    def explain(evidence: LineageEvidence) -> dict:
        successful_tools = [t for t in evidence.tool_calls if t.success]
        signals = {
            "has_semantic": any(
                t.tool_name == "semantic_query" and t.success for t in successful_tools
            ),
            "has_sql": len(evidence.sql_executions) > 0,
            "has_memory_support": len(evidence.retrieved_memories) > 0,
            "has_validation": len(evidence.validation_checks) > 0,
            "has_errors": any(not t.success for t in evidence.tool_calls),
        }
        if signals["has_semantic"] and signals["has_validation"] and not signals["has_errors"]:
            tier = "High"
        elif (signals["has_sql"] or signals["has_memory_support"]) and not signals["has_errors"]:
            tier = "Medium"
        else:
            tier = "Low"
        return {"tier": tier, "signals": signals}

    @staticmethod
    def score(evidence: LineageEvidence) -> str:
        return ConfidenceScorer.explain(evidence)["tier"]
```
Then, where the lineage card is rendered, include `ConfidenceScorer.explain(...)["signals"]` and label the field "Confidence (heuristic)" so the tier is transparent rather than implying calibrated precision.

- [ ] **Step 4: Run tests, verify pass; commit**

```bash
python -m pytest tests/test_lineage_capture.py -q
git add src/vanna/core/lineage/confidence.py tests/test_lineage_capture.py src/vanna/core/agent/agent.py
git commit -m "refactor(lineage): expose confidence signals; label tier as heuristic"
```

### Task D4: Remove committed query-result artifacts; ignore them going forward

**Files:**
- Delete: `37a8eec1ce19687d/`, `e606e38b0d8c19b2/`, `bb82030dbc2bcaba/` (committed CSV dirs at repo root)
- Modify: `.gitignore`

- [ ] **Step 1: Remove the artifact directories**

```bash
cd /Users/mac/Documents/Claude/Projects/vanna-v3
git rm -r --quiet 37a8eec1ce19687d e606e38b0d8c19b2 bb82030dbc2bcaba
```

- [ ] **Step 2: Ignore future artifacts** — append to `.gitignore`:
```
# Generated query-result artifacts (written by RunSqlTool / LocalFileSystem)
query_results_*.csv
**/query_results_*.csv
```

- [ ] **Step 3: Verify + commit**

```bash
git status --porcelain | head
git add .gitignore
git commit -m "chore: remove committed query-result CSV artifacts and gitignore them"
```

---

## Phase E: Docs & version honesty

### Task E1: Rewrite README and v3 docs to match reality

**Files:** `README.md`, `docs/v3/architecture-and-design.md`, `docs/v3/implementation-plan.md` (if it overclaims)

- [ ] **Step 1:** Update the README "What's New in 3.0" / "Why" sections so every bullet maps to shipped behavior: semantic routing now ships a real `FileSemanticAdapter`; read-only SQL is AST-validated and connection-enforced; RLS uses the safe `apply_row_filter` helper; the eval gate runs a real deterministic evaluation. Remove or clearly label anything still illustrative. Remove the "community fork builds on v2.0.2" CVE-bearing framing now that legacy is gone; state the lineage honestly (forked from vanna-ai/vanna v2.0.2, legacy adapter removed).
- [ ] **Step 2:** In `docs/v3/architecture-and-design.md`, remove the "legacy APIs and adapter path remain supported" line (no longer true) and update the chart-generation section to reflect declarative `ChartSpec` only.
- [ ] **Step 3: Commit**
```bash
git add README.md docs/v3/
git commit -m "docs: rewrite README and v3 architecture to match shipped behavior"
```

### Task E2: Unify the version to 3.0.0

**Files:** `pyproject.toml` (line ~7), `src/vanna/__init__.py` (line ~9), `frontends/webcomponent/package.json` (line ~4)

- [ ] **Step 1:** Set all three to `3.0.0`:
  - `pyproject.toml`: `version = "3.0.0"` (and update `authors`/`description` if desired to reflect the fork).
  - `src/vanna/__init__.py`: `__version__ = "3.0.0"`.
  - `frontends/webcomponent/package.json`: `"version": "3.0.0"`.
- [ ] **Step 2: Verify + commit**
```bash
python -c "import vanna; print(vanna.__version__)"   # expect 3.0.0
grep -n "version" pyproject.toml | head -1
git add pyproject.toml src/vanna/__init__.py frontends/webcomponent/package.json
git commit -m "chore: unify version to 3.0.0 across package, module, and web component"
```

### Task E3: Update migration/contributing docs for the legacy removal

**Files:** `MIGRATION_GUIDE.md`, `CONTRIBUTING.md`, `README_LEGACY.md`

- [ ] **Step 1:** `MIGRATION_GUIDE.md` — remove the 0.x→2.0 legacy-adapter content (the `from vanna.legacy.adapter import LegacyVannaAdapter` examples and the deprecated-strategy table). Replace with a short note: "The legacy adapter was removed in 3.0; this fork targets the v2.0+ agent architecture directly." Or delete the file if it no longer carries useful content.
- [ ] **Step 2:** `CONTRIBUTING.md` — remove the legacy-adapter section (the `test_legacy_adapter.py`, `tox -e py311-legacy`, and "LegacyVannaAdapter bridges…" references).
- [ ] **Step 3:** `README_LEGACY.md` — delete (it documents the upstream pre-2.0 project and is now misleading), or keep only if you want the historical record; if kept, add a banner that it describes the removed legacy path.
- [ ] **Step 4: Verify no stale legacy mentions remain in docs + commit**
```bash
grep -rn "LegacyVannaAdapter\|vanna.legacy\|tox -e py311-legacy" *.md docs/ || echo "clean"
git add -A
git commit -m "docs: drop legacy-adapter migration/contributing content (legacy removed in 3.0)"
```

---

## Phase F: Delivery

### Task F1: Full verification

**Files:** `docs/superpowers/specs/2026-06-18-vanna-v3-deslop-design.md` (mark status)

- [ ] **Step 1: Full gates**
```bash
cd /Users/mac/Documents/Claude/Projects/vanna-v3
source .venv/bin/activate
python -m pytest -m "not integration" -q 2>&1 | tail -5
ruff check src tests
mypy src 2>&1 | tail -20   # match the repo's existing mypy scope/config
```
Expected: tests green; ruff clean; mypy no new errors vs baseline. Fix any fallout before proceeding.
- [ ] **Step 2: Confirm CVEs gone**
```bash
test -d src/vanna/legacy && echo "STILL PRESENT" || echo "legacy removed"
grep -rn "exec(" src/vanna/tools src/vanna/core || echo "no exec in active code"
```
- [ ] **Step 3:** Update the spec header `Status:` to `Implemented`; commit.

### Task F2: Push branch and open PR (unarchive first)

**Files:** none (GitHub operations)

- [ ] **Step 1: Unarchive the repo** (it is currently archived/read-only):
```bash
gh api -X PATCH repos/xhu96/vanna-v3 -f archived=false
```
- [ ] **Step 2: Push the branch**
```bash
git push -u origin cleanup/v3-deslop
```
- [ ] **Step 3: Open the PR** with a structured body summarizing: security hardening (AST read-only + connection-level + RLS helper), real features (FileSemanticAdapter, real eval gate, weight-aware memory), legacy deletion (CVE-2026-4513/4229 removed), de-slop (Flask async, artifacts, version unify), and the before/after test + eval numbers:
```bash
gh pr create --repo xhu96/vanna-v3 --base main --head cleanup/v3-deslop \
  --title "De-slop & harden vanna-v3 (security, real features, legacy removal)" \
  --body-file docs/superpowers/specs/2026-06-18-vanna-v3-deslop-design.md
```
- [ ] **Step 4:** Report the PR URL back to the user. Leave merge to the user (their review gate). Optionally re-archive only if the user requests it.

---

## Self-Review (completed by plan author)

**Spec coverage:** A (security) → Tasks A1–A4; B (build for real) → B1–B3; C (legacy) → C1; D (de-slop) → D1–D4; E (docs/version) → E1–E3; F (deliver) → F1–F2. Every spec workstream maps to ≥1 task. The extra schema_sync PRAGMA injection (found during gathering) is folded into A2; the non-SELECT result bug (found during gathering) is A4.

**Placeholder scan:** The only deliberately-deferred bodies are `build_variant()` and the exact eval imports in B2 Step 6 — these are gated behind B2 Step 1 (read `llm_comparison.py`/`runner.py` and reuse the existing construction verbatim), because inventing the Agent/runner construction would risk undefined references. All other steps contain complete code or exact commands.

**Type consistency:** Uses the verified field/method names: `SemanticPlanHint(coverage, reason, request)`, `SemanticCoverage=Literal["full","partial","missing"]`, `SemanticQueryRequest(metric, dimensions, filters, time_grain, limit, order_by)`, `ToolMemory(... metadata)`, `ToolMemorySearchResult(memory, similarity_score, rank)`, `EvaluationReport.pass_rate()/average_score()`, `MockLlmService` interface for `ScriptedLlmService`. sqlglot expression names flagged as version-sensitive with a discovery command.
