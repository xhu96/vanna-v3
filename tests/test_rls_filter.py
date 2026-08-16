"""Execution-level regressions for recursive tenant row filtering."""

from __future__ import annotations

import sqlite3

import pytest
import sqlglot

from vanna.security.rls import (
    RowFilterPolicy,
    apply_row_filter,
    apply_row_policies,
)


@pytest.fixture
def tenant_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            region TEXT NOT NULL,
            secret TEXT NOT NULL,
            amount INTEGER NOT NULL
        );
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE tenant_anchor (
            id INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL
        );
        CREATE TABLE dimensions (label TEXT NOT NULL);

        INSERT INTO orders VALUES
            (1, 'tenant-a', 10, 'west', 'A-only', 100),
            (2, 'tenant-a', 11, 'east', 'A-east', 200),
            (3, 'tenant-b', 20, 'west', 'B-secret', 900);
        INSERT INTO customers VALUES
            (10, 'tenant-a', 'Alice'),
            (11, 'tenant-a', 'Aster'),
            (20, 'tenant-b', 'Bob');
        INSERT INTO tenant_anchor VALUES (1, 'tenant-a'), (2, 'tenant-b');
        INSERT INTO dimensions VALUES ('all-regions');
        """
    )
    return connection


def _run(connection: sqlite3.Connection, sql: str) -> list[tuple[object, ...]]:
    return connection.execute(sql).fetchall()


def test_adds_pre_source_filter_when_absent(tenant_db: sqlite3.Connection) -> None:
    out = apply_row_filter(
        "SELECT id FROM orders ORDER BY id", "tenant_id", "tenant-a", dialect="sqlite"
    )
    assert _run(tenant_db, out) == [(1,), (2,)]
    assert len(list(sqlglot.parse_one(out).find_all(sqlglot.exp.Where))) == 1


def test_composes_with_existing_where_and_group_by(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_filter(
        "SELECT region, SUM(amount) FROM orders WHERE amount > 50 GROUP BY region ORDER BY region",
        "tenant_id",
        "tenant-a",
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [("east", 200), ("west", 100)]


def test_injection_value_is_a_single_literal(tenant_db: sqlite3.Connection) -> None:
    malicious = "tenant-a' OR '1'='1"
    out = apply_row_filter(
        "SELECT id FROM orders", "tenant_id", malicious, dialect="sqlite"
    )
    parsed = sqlglot.parse_one(out, read="sqlite")
    literals = [
        node.this for node in parsed.find_all(sqlglot.exp.Literal) if node.is_string
    ]
    assert malicious in literals
    assert parsed.find(sqlglot.exp.Or) is None
    assert _run(tenant_db, out) == []


def test_join_filters_each_physical_alias(tenant_db: sqlite3.Connection) -> None:
    out = apply_row_filter(
        """
        SELECT o.id, c.name
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        ORDER BY o.id
        """,
        "tenant_id",
        "tenant-a",
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1, "Alice"), (2, "Aster")]
    assert out.count("tenant_id = 'tenant-a'") == 2


def test_left_join_filter_preserves_outer_join_semantics(
    tenant_db: sqlite3.Connection,
) -> None:
    tenant_db.execute(
        "INSERT INTO orders VALUES (4, 'tenant-a', 999, 'west', 'A-orphan', 50)"
    )
    out = apply_row_filter(
        """
        SELECT o.id, c.name
        FROM orders o
        LEFT JOIN customers c ON c.id = o.customer_id
        ORDER BY o.id
        """,
        "tenant_id",
        "tenant-a",
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1, "Alice"), (2, "Aster"), (4, None)]


def test_self_join_filters_every_alias(tenant_db: sqlite3.Connection) -> None:
    out = apply_row_filter(
        "SELECT a.id, b.id FROM orders a JOIN orders b ON a.region = b.region ORDER BY a.id, b.id",
        "tenant_id",
        "tenant-a",
        dialect="sqlite",
    )
    rows = _run(tenant_db, out)
    assert rows == [(1, 1), (2, 2)]
    assert out.count("tenant_id = 'tenant-a'") == 2


@pytest.mark.parametrize(
    "sql",
    [
        "WITH visible AS (SELECT id, secret FROM orders) SELECT secret FROM visible ORDER BY id",
        "SELECT secret FROM (SELECT id, secret FROM orders) visible ORDER BY id",
        "SELECT (SELECT group_concat(secret, ',') FROM orders) FROM tenant_anchor",
        "SELECT a.id, (SELECT group_concat(o.secret, ',') FROM orders o WHERE o.tenant_id = a.tenant_id) FROM tenant_anchor a",
    ],
)
def test_nested_cte_derived_and_correlated_sources_do_not_leak(
    tenant_db: sqlite3.Connection, sql: str
) -> None:
    out = apply_row_filter(sql, "tenant_id", "tenant-a", dialect="sqlite")
    rows = _run(tenant_db, out)
    rendered = repr(rows)
    assert "B-secret" not in rendered
    assert "tenant-b" not in rendered
    assert rows


@pytest.mark.parametrize("operator", ["UNION", "UNION ALL", "INTERSECT", "EXCEPT"])
def test_every_set_operation_arm_is_filtered(
    tenant_db: sqlite3.Connection, operator: str
) -> None:
    sql = f"SELECT id FROM orders {operator} SELECT id FROM orders"
    out = apply_row_filter(sql, "tenant_id", "tenant-a", dialect="sqlite")
    rows = _run(tenant_db, out)
    assert all(row[0] in {1, 2} for row in rows)
    assert "3" not in repr(rows)
    assert out.count("tenant_id = 'tenant-a'") == 2


def test_set_operation_inside_derived_table_is_filtered(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_filter(
        "SELECT id FROM (SELECT id FROM orders UNION ALL SELECT id FROM orders) x ORDER BY id",
        "tenant_id",
        "tenant-a",
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1,), (1,), (2,), (2,)]


def test_recursive_cte_filters_seed_and_recursive_physical_sources(
    tenant_db: sqlite3.Connection,
) -> None:
    tenant_db.executescript(
        """
        CREATE TABLE nodes (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER,
            tenant_id TEXT NOT NULL
        );
        INSERT INTO nodes VALUES
            (1, NULL, 'tenant-a'),
            (2, 1, 'tenant-a'),
            (3, NULL, 'tenant-b'),
            (4, 3, 'tenant-b');
        """
    )
    out = apply_row_filter(
        """
        WITH RECURSIVE tree(id) AS (
            SELECT id FROM nodes WHERE parent_id IS NULL
            UNION ALL
            SELECT n.id FROM nodes n JOIN tree t ON n.parent_id = t.id
        )
        SELECT id FROM tree ORDER BY id
        """,
        "tenant_id",
        "tenant-a",
        protected_tables={"nodes"},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1,), (2,)]
    assert out.count("tenant_id = 'tenant-a'") == 2


def test_explicit_public_tables_leave_dimensions_unmodified(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_filter(
        "SELECT o.id, d.label FROM orders o CROSS JOIN dimensions d ORDER BY o.id",
        "tenant_id",
        "tenant-a",
        protected_tables={"orders"},
        allowed_unfiltered_tables={"dimensions"},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1, "all-regions"), (2, "all-regions")]
    assert "dimensions WHERE tenant_id" not in out


def test_catalogued_protected_tables_may_be_absent_from_a_query(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_filter(
        "SELECT id FROM orders ORDER BY id",
        "tenant_id",
        "tenant-a",
        protected_tables={"orders", "customers", "invoices"},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1,), (2,)]


def test_multiple_policies_are_applied_before_scan(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_policies(
        "SELECT secret FROM orders",
        [
            RowFilterPolicy("tenant_id", "tenant-a", frozenset({"orders"})),
            RowFilterPolicy("region", "west", frozenset({"orders"})),
        ],
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [("A-only",)]


def test_qualified_and_quoted_identifiers_are_supported(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_filter(
        "SELECT main.orders.id FROM main.orders ORDER BY main.orders.id",
        '"tenant_id"',
        "tenant-a",
        protected_tables={'"main"."orders"'},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1,), (2,)]
    assert '"tenant_id"' in out
    assert "main.orders" in out
    assert "SELECT _vanna_rls_" in out


def test_schema_qualified_star_is_retargeted(
    tenant_db: sqlite3.Connection,
) -> None:
    out = apply_row_filter(
        "SELECT main.orders.* FROM main.orders ORDER BY main.orders.id",
        "tenant_id",
        "tenant-a",
        protected_tables={"main.orders"},
        dialect="sqlite",
    )
    rows = _run(tenant_db, out)
    assert [row[0] for row in rows] == [1, 2]
    assert "main.orders.*" not in out


def test_child_scope_correlated_qualified_reference_is_retargeted(
    tenant_db: sqlite3.Connection,
) -> None:
    tenant_db.execute("ATTACH DATABASE ':memory:' AS aux")
    tenant_db.executescript(
        """
        CREATE TABLE aux.orders (
            id INTEGER PRIMARY KEY,
            parent INTEGER NOT NULL,
            tenant_id TEXT NOT NULL
        );
        INSERT INTO aux.orders VALUES
            (100, 1, 'tenant-a'),
            (101, 1, 'tenant-b'),
            (102, 2, 'tenant-a');
        """
    )
    out = apply_row_filter(
        """
        SELECT main.orders.id,
               (SELECT COUNT(*) FROM aux.orders
                WHERE aux.orders.parent = main.orders.id)
        FROM main.orders
        ORDER BY main.orders.id
        """,
        "tenant_id",
        "tenant-a",
        protected_tables={"main.orders", "aux.orders"},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1, 1), (2, 1)]
    assert "main.orders.id" not in out
    assert "aux.orders.parent" not in out


def test_child_scope_short_correlated_reference_remains_valid(
    tenant_db: sqlite3.Connection,
) -> None:
    tenant_db.execute("ATTACH DATABASE ':memory:' AS aux")
    tenant_db.executescript(
        """
        CREATE TABLE aux.children (
            id INTEGER PRIMARY KEY,
            parent INTEGER NOT NULL,
            tenant_id TEXT NOT NULL
        );
        INSERT INTO aux.children VALUES
            (100, 1, 'tenant-a'),
            (101, 1, 'tenant-b'),
            (102, 2, 'tenant-a');
        """
    )
    out = apply_row_filter(
        """
        SELECT main.orders.id,
               (SELECT COUNT(*) FROM aux.children
                WHERE aux.children.parent = orders.id)
        FROM main.orders
        ORDER BY main.orders.id
        """,
        "tenant_id",
        "tenant-a",
        protected_tables={"main.orders", "aux.children"},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1, 1), (2, 1)]


def test_same_scope_qualified_sources_with_same_name_are_isolated(
    tenant_db: sqlite3.Connection,
) -> None:
    tenant_db.execute("ATTACH DATABASE ':memory:' AS aux")
    tenant_db.executescript(
        """
        CREATE TABLE aux.orders (
            id INTEGER PRIMARY KEY,
            parent INTEGER NOT NULL,
            tenant_id TEXT NOT NULL
        );
        INSERT INTO aux.orders VALUES
            (100, 1, 'tenant-a'),
            (101, 1, 'tenant-b'),
            (102, 3, 'tenant-a');
        """
    )
    out = apply_row_filter(
        """
        SELECT main.orders.id, aux.orders.id
        FROM main.orders
        JOIN aux.orders ON aux.orders.parent = main.orders.id
        ORDER BY main.orders.id, aux.orders.id
        """,
        "tenant_id",
        "tenant-a",
        protected_tables={"main.orders", "aux.orders"},
        dialect="sqlite",
    )
    assert _run(tenant_db, out) == [(1, 100)]
    assert "main.orders.id" not in out
    assert "aux.orders.id" not in out


@pytest.mark.parametrize(
    "sql",
    [
        """
        SELECT orders.id
        FROM main.orders
        JOIN aux.orders ON aux.orders.parent = main.orders.id
        ORDER BY main.orders.id
        """,
        """
        SELECT main.orders.id
        FROM main.orders
        JOIN aux.orders ON aux.orders.parent = main.orders.id
        ORDER BY orders.id
        """,
        """
        SELECT main.orders.id
        FROM main.orders
        JOIN aux.orders ON orders.parent = main.orders.id
        """,
    ],
)
def test_same_scope_ambiguous_short_qualifiers_fail_closed(sql: str) -> None:
    with pytest.raises(ValueError, match="Ambiguous qualified column"):
        apply_row_filter(
            sql,
            "tenant_id",
            "tenant-a",
            protected_tables={"main.orders", "aux.orders"},
            dialect="sqlite",
        )


@pytest.mark.parametrize("projection", ["main.orders.id", "main.orders.*"])
def test_identical_qualified_sources_without_aliases_fail_closed(
    projection: str,
) -> None:
    with pytest.raises(ValueError, match="Ambiguous duplicate physical source"):
        apply_row_filter(
            f"""
            SELECT {projection}
            FROM main.orders
            JOIN main.orders ON main.orders.parent = main.orders.id
            """,
            "tenant_id",
            "tenant-a",
            protected_tables={"main.orders"},
            dialect="sqlite",
        )


def test_unknown_and_ambiguous_protected_sources_fail_closed() -> None:
    with pytest.raises(ValueError, match="no row policy"):
        apply_row_filter(
            "SELECT * FROM orders",
            "tenant_id",
            "tenant-a",
            protected_tables={"missing"},
            dialect="sqlite",
        )

    with pytest.raises(ValueError, match="no row policy"):
        apply_row_filter(
            "SELECT o.id FROM orders o JOIN shadow_orders s ON s.id = o.id",
            "tenant_id",
            "tenant-a",
            protected_tables={"orders"},
            dialect="postgres",
        )

    allowed = apply_row_filter(
        "SELECT o.id FROM orders o JOIN dimensions d ON d.id = o.id",
        "tenant_id",
        "tenant-a",
        protected_tables={"orders"},
        allowed_unfiltered_tables={"dimensions"},
        dialect="postgres",
    )
    assert "dimensions AS d" in allowed

    with pytest.raises(ValueError, match="Ambiguous"):
        apply_row_filter(
            "SELECT * FROM alpha.orders a JOIN beta.orders b ON a.id = b.id",
            "tenant_id",
            "tenant-a",
            protected_tables={"orders"},
        )


def test_public_table_allowlist_requires_exact_physical_identity() -> None:
    with pytest.raises(ValueError, match="no row policy"):
        apply_row_filter(
            "SELECT * FROM secret.regions",
            "tenant_id",
            "tenant-a",
            protected_tables={"orders"},
            allowed_unfiltered_tables={"regions"},
            dialect="postgres",
        )

    allowed = apply_row_filter(
        "SELECT * FROM public.regions",
        "tenant_id",
        "tenant-a",
        protected_tables={"orders"},
        allowed_unfiltered_tables={"public.regions"},
        dialect="postgres",
    )
    assert allowed == "SELECT * FROM public.regions"


def test_public_table_allowlist_preserves_quoted_case_identity() -> None:
    with pytest.raises(ValueError, match="no row policy"):
        apply_row_filter(
            'SELECT * FROM "Regions"',
            "tenant_id",
            "tenant-a",
            protected_tables={"orders"},
            allowed_unfiltered_tables={"regions"},
            dialect="postgres",
        )

    allowed = apply_row_filter(
        'SELECT * FROM "Regions"',
        "tenant_id",
        "tenant-a",
        protected_tables={"orders"},
        allowed_unfiltered_tables={'"Regions"'},
        dialect="postgres",
    )
    assert allowed == 'SELECT * FROM "Regions"'


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders; SELECT * FROM orders",
        "DELETE FROM orders",
        "this is not SQL",
    ],
)
def test_invalid_or_non_query_sql_fails_closed(sql: str) -> None:
    with pytest.raises(ValueError):
        apply_row_filter(sql, "tenant_id", "tenant-a", dialect="sqlite")


def test_unsafe_policy_identifiers_and_values_fail_closed() -> None:
    with pytest.raises(ValueError, match="Unsafe filter column"):
        apply_row_filter("SELECT * FROM orders", "tenant_id; DROP TABLE orders", "x")
    with pytest.raises(ValueError, match="finite"):
        RowFilterPolicy("tenant_id", float("nan"))


def test_constant_query_without_physical_sources_remains_available() -> None:
    assert apply_row_filter("SELECT 1", "tenant_id", "tenant-a") == "SELECT 1"
