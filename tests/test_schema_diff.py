"""Canonical schema hashing and diff regressions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from vanna.capabilities.schema_catalog import SchemaColumn, SchemaSnapshot
from vanna.services.schema_sync import PortableSchemaCatalogService


def column(
    name: str,
    data_type: str = "integer",
    *,
    nullable: bool = False,
    ordinal: int = 1,
) -> SchemaColumn:
    return SchemaColumn(
        schema_name="public",
        table_name="orders",
        column_name=name,
        data_type=data_type,
        is_nullable=nullable,
        ordinal_position=ordinal,
    )


def snapshot(
    snapshot_id: str,
    version: int,
    columns: list[SchemaColumn],
    previous_snapshot_id: str | None = None,
) -> SchemaSnapshot:
    return SchemaSnapshot(
        snapshot_id=snapshot_id,
        tenant_id="tenant-a",
        schema_version=version,
        captured_at=datetime(2026, 8, version, tzinfo=timezone.utc),
        dialect="postgres",
        schema_hash=PortableSchemaCatalogService.compute_hash(columns),
        previous_snapshot_id=previous_snapshot_id,
        columns=columns,
    )


def test_canonical_hash_is_order_independent_and_sensitive_to_descriptors() -> None:
    first = column("id", ordinal=1)
    second = column("status", "text", nullable=True, ordinal=2)

    ordered = PortableSchemaCatalogService.compute_hash([first, second])
    reversed_hash = PortableSchemaCatalogService.compute_hash([second, first])
    changed = PortableSchemaCatalogService.compute_hash(
        [first, second.model_copy(update={"is_nullable": False})]
    )

    assert ordered == reversed_hash
    assert ordered != changed
    assert len(ordered) == 64


def test_diff_tracks_added_removed_changed_entities_and_provenance() -> None:
    previous = snapshot(
        "snap_previous",
        1,
        [column("id"), column("amount", ordinal=2)],
    )
    current = snapshot(
        "snap_current",
        2,
        [
            column("id", "bigint"),
            column("status", "text", nullable=True, ordinal=2),
        ],
        previous_snapshot_id=previous.snapshot_id,
    )

    diff = PortableSchemaCatalogService.diff_snapshots(previous, current)

    assert diff.has_drift is True
    assert diff.previous_schema_hash == previous.schema_hash
    assert diff.current_schema_hash == current.schema_hash
    assert diff.previous_schema_version == 1
    assert diff.current_schema_version == 2
    assert diff.added_entities == ["public.orders.status"]
    assert diff.removed_entities == ["public.orders.amount"]
    assert diff.changed_entities == ["public.orders.id"]


def test_equal_snapshots_have_no_drift() -> None:
    current = snapshot("snap_current", 1, [column("id")])
    diff = PortableSchemaCatalogService.diff_snapshots(current, current)

    assert diff.has_drift is False
    assert diff.added_columns == []
    assert diff.removed_columns == []
    assert diff.changed_columns == []


def test_snapshot_models_are_closed_canonical_and_reject_duplicate_columns() -> None:
    first = column("id", ordinal=1)
    second = column("status", "text", ordinal=2)
    result = snapshot("snap_ordered", 1, [second, first])
    assert [item.column_name for item in result.columns] == ["id", "status"]

    with pytest.raises(ValidationError, match="duplicate columns"):
        snapshot("snap_duplicate", 1, [first, first])

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SchemaColumn.model_validate(
            {
                **first.model_dump(),
                "unexpected": "active content",
            }
        )

    with pytest.raises(ValidationError, match="hash does not match"):
        SchemaSnapshot.model_validate(
            {
                **result.model_dump(),
                "schema_hash": "0" * 64,
            }
        )


def test_entity_ids_escape_dotted_components_without_changing_simple_names() -> None:
    simple = column("id")
    dotted_schema = SchemaColumn(
        schema_name="a.b",
        table_name="c",
        column_name="d",
        data_type="integer",
    )
    dotted_table = SchemaColumn(
        schema_name="a",
        table_name="b.c",
        column_name="d",
        data_type="integer",
    )

    assert simple.entity_id == "public.orders.id"
    assert dotted_schema.entity_id == "a%2Eb.c.d"
    assert dotted_table.entity_id == "a.b%2Ec.d"
    assert dotted_schema.entity_id != dotted_table.entity_id
    assert len({item.entity_id for item in (dotted_schema, dotted_table)}) == 2
