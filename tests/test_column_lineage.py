"""Tests for column-level lineage extraction."""

import pytest

pytest.importorskip("sqlglot", reason="sqlglot not installed; run: pip install vanna[de]")

from vanna.core.lineage.column_lineage import extract_column_lineage
from vanna.core.lineage.models import ColumnLineageEdge, LineageEvidence
from vanna.core.lineage.collector import LineageCollector


# ---------------------------------------------------------------------------
# extract_column_lineage — unit tests
# ---------------------------------------------------------------------------


def test_simple_select_qualified_columns():
    sql = "SELECT o.id, o.total FROM orders o"
    edges = extract_column_lineage(sql)
    columns = {(e.source_table, e.column) for e in edges}
    assert ("o", "id") in columns
    assert ("o", "total") in columns


def test_simple_select_unqualified_columns():
    sql = "SELECT id, name FROM customers"
    edges = extract_column_lineage(sql)
    columns = {e.column for e in edges}
    assert "id" in columns
    assert "name" in columns
    # No table qualifier → source_table is "unknown"
    assert all(e.source_table == "unknown" for e in edges)


def test_alias_captured():
    sql = "SELECT revenue * 0.1 AS tax FROM sales"
    edges = extract_column_lineage(sql)
    aliases = {e.alias for e in edges if e.alias}
    assert "tax" in aliases


def test_join_query():
    sql = """
        SELECT c.name, o.total
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
    """
    edges = extract_column_lineage(sql)
    columns = {(e.source_table, e.column) for e in edges}
    assert ("c", "name") in columns
    assert ("o", "total") in columns


def test_wildcard_select():
    sql = "SELECT * FROM products"
    edges = extract_column_lineage(sql)
    assert any(e.column == "*" for e in edges)


def test_subquery():
    sql = """
        SELECT sub.total
        FROM (SELECT SUM(amount) AS total FROM payments) sub
    """
    edges = extract_column_lineage(sql)
    # Should find "total" from the outer SELECT
    assert any(e.column == "total" for e in edges)


def test_cte():
    sql = """
        WITH regional AS (
            SELECT region, SUM(revenue) AS rev FROM sales GROUP BY region
        )
        SELECT region, rev FROM regional
    """
    edges = extract_column_lineage(sql)
    columns = {e.column for e in edges}
    assert "region" in columns
    assert "rev" in columns


def test_malformed_sql_returns_empty_list():
    """Must never raise — returns [] for unparseable input."""
    result = extract_column_lineage("THIS IS NOT SQL !!!@#$")
    assert isinstance(result, list)


def test_empty_string_returns_empty_list():
    result = extract_column_lineage("")
    assert result == []


def test_dialect_parameter_accepted():
    sql = "SELECT id, name FROM `my_table`"
    # bigquery uses backtick-quoted identifiers
    edges = extract_column_lineage(sql, dialect="bigquery")
    assert isinstance(edges, list)


def test_returns_list_of_column_lineage_edge():
    sql = "SELECT id FROM orders"
    edges = extract_column_lineage(sql)
    assert all(isinstance(e, ColumnLineageEdge) for e in edges)


def test_aggregate_function_captures_inner_column():
    sql = "SELECT SUM(amount) AS total_revenue FROM transactions"
    edges = extract_column_lineage(sql)
    columns = {e.column for e in edges}
    assert "amount" in columns


# ---------------------------------------------------------------------------
# LineageCollector integration — column_lineage field populated
# ---------------------------------------------------------------------------


def test_collector_populates_column_lineage():
    collector = LineageCollector()
    collector.record_tool_result(
        tool_name="run_sql",
        success=True,
        metadata={
            "executed_sql": "SELECT id, name FROM customers",
            "row_count": 5,
        },
    )
    evidence = collector.finalize()
    assert len(evidence.column_lineage) > 0
    columns = {e.column for e in evidence.column_lineage}
    assert "id" in columns
    assert "name" in columns


def test_collector_column_lineage_empty_when_no_sql():
    collector = LineageCollector()
    collector.record_tool_result(
        tool_name="send_email",
        success=True,
        metadata={},
    )
    evidence = collector.finalize()
    assert evidence.column_lineage == []


def test_collector_column_lineage_field_defaults_empty():
    evidence = LineageEvidence()
    assert evidence.column_lineage == []


def test_collector_to_markdown_includes_column_lineage():
    collector = LineageCollector()
    collector.record_tool_result(
        tool_name="run_sql",
        success=True,
        metadata={"executed_sql": "SELECT amount AS revenue FROM sales"},
    )
    md = collector.to_markdown()
    assert "Column lineage" in md
