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
    # exactly one WHERE, and no OR injected at the AST level: the malicious
    # value is bound as an escaped literal (so its " OR " text survives only
    # *inside* that literal), never parsed as a boolean OR predicate.
    assert len(list(parsed.find_all(sqlglot.exp.Where))) == 1
    assert parsed.find(sqlglot.exp.Or) is None


def test_applies_with_group_by():
    out = apply_row_filter(
        "SELECT region, SUM(amount) FROM orders GROUP BY region",
        "tenant_id",
        "tenant-a",
    )
    parsed = sqlglot.parse_one(out)
    assert parsed.find(sqlglot.exp.Where) is not None
    assert parsed.find(sqlglot.exp.Group) is not None
