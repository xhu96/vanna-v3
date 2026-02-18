"""Portable schema snapshot + drift sync service."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from vanna.capabilities.schema_catalog import (
    SchemaCatalog,
    SchemaColumn,
    SchemaDiff,
    SchemaSnapshot,
    SchemaSyncResult,
)
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext


class PortableSchemaCatalogService(SchemaCatalog):
    """Schema catalog implementation using portable SQL catalog queries."""

    def __init__(
        self,
        sql_runner: SqlRunner,
        *,
        persist_path: str = ".vanna/schema_catalog_latest.json",
        dialect: str = "unknown",
        cron_schedule: Optional[str] = None,
    ):
        self.sql_runner = sql_runner
        self.persist_path = Path(persist_path)
        self.dialect = dialect
        self.cron_schedule = cron_schedule
        self._last_scheduled_sync_minute: Optional[str] = None

    async def capture_snapshot(self, context: ToolContext) -> SchemaSnapshot:
        columns = await self._fetch_columns(context)
        schema_hash = self._compute_hash(columns)
        return SchemaSnapshot(
            snapshot_id=f"snap_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            dialect=self.dialect,
            schema_hash=schema_hash,
            columns=columns,
        )

    async def sync(self, context: ToolContext) -> SchemaSyncResult:
        previous = await self.get_latest_snapshot()
        current = await self.capture_snapshot(context)
        diff = self._diff_snapshots(previous, current)
        self._persist_snapshot(current)

        if diff.has_drift:
            await self._patch_memory_for_drift(context, diff)

        return SchemaSyncResult(snapshot=current, diff=diff)

    async def run_scheduled_sync_if_due(
        self, context: ToolContext, now: Optional[datetime] = None
    ) -> Optional[SchemaSyncResult]:
        """Cron-compatible scheduler hook (5-field cron expression)."""
        if not self.cron_schedule:
            return None

        now = now or datetime.utcnow()
        if not _cron_matches(self.cron_schedule, now):
            return None

        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if self._last_scheduled_sync_minute == minute_key:
            return None

        self._last_scheduled_sync_minute = minute_key
        return await self.sync(context)

    async def get_latest_snapshot(self) -> Optional[SchemaSnapshot]:
        if not self.persist_path.exists():
            return None
        payload = json.loads(self.persist_path.read_text(encoding="utf-8"))
        return SchemaSnapshot.model_validate(payload["snapshot"])

    async def _fetch_columns(self, context: ToolContext) -> List[SchemaColumn]:
        # Portable baseline query for most warehouse/OLTP engines.
        info_schema_sql = """
            SELECT
                table_schema AS schema_name,
                table_name,
                column_name,
                data_type,
                CASE
                    WHEN is_nullable IN ('YES', 'yes', 'Y', 'y', 'true', 'TRUE') THEN 1
                    ELSE 0
                END AS is_nullable
            FROM information_schema.columns
            ORDER BY table_schema, table_name, ordinal_position
        """
        try:
            df = await self.sql_runner.run_sql(
                RunSqlToolArgs(sql=info_schema_sql), context
            )
            if not df.empty:
                return self._columns_from_dataframe(df)
        except Exception:
            # Continue to sqlite fallback for engines without information_schema.
            pass

        return await self._fetch_sqlite_columns(context)

    async def _fetch_sqlite_columns(self, context: ToolContext) -> List[SchemaColumn]:
        tables_df = await self.sql_runner.run_sql(
            RunSqlToolArgs(
                sql="""
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """
            ),
            context,
        )

        columns: List[SchemaColumn] = []
        for table_name in tables_df["name"].tolist():
            pragma_df = await self.sql_runner.run_sql(
                RunSqlToolArgs(sql=f"PRAGMA table_info('{table_name}')"),
                context,
            )
            for _, row in pragma_df.iterrows():
                columns.append(
                    SchemaColumn(
                        schema_name="main",
                        table_name=table_name,
                        column_name=str(row["name"]),
                        data_type=str(row["type"]),
                        is_nullable=bool(int(row.get("notnull", 0)) == 0),
                    )
                )

        return columns

    def _columns_from_dataframe(self, df: pd.DataFrame) -> List[SchemaColumn]:
        columns: List[SchemaColumn] = []
        for _, row in df.iterrows():
            columns.append(
                SchemaColumn(
                    schema_name=str(row.get("schema_name"))
                    if row.get("schema_name") is not None
                    else None,
                    table_name=str(row.get("table_name")),
                    column_name=str(row.get("column_name")),
                    data_type=str(row.get("data_type")),
                    is_nullable=bool(int(row.get("is_nullable", 0))),
                )
            )
        return columns

    def _compute_hash(self, columns: List[SchemaColumn]) -> str:
        normalized = sorted(
            [
                {
                    "schema_name": c.schema_name or "",
                    "table_name": c.table_name,
                    "column_name": c.column_name,
                    "data_type": c.data_type,
                    "is_nullable": c.is_nullable,
                }
                for c in columns
            ],
            key=lambda c: (
                c["schema_name"],
                c["table_name"],
                c["column_name"],
                c["data_type"],
            ),
        )
        content = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _persist_snapshot(self, snapshot: SchemaSnapshot) -> None:
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.persist_path.write_text(
            json.dumps({"snapshot": snapshot.model_dump(mode="json")}, indent=2),
            encoding="utf-8",
        )

    def _column_key(self, column: SchemaColumn) -> Tuple[str, str, str]:
        return (column.schema_name or "", column.table_name, column.column_name)

    def _to_index(
        self, columns: Iterable[SchemaColumn]
    ) -> Dict[Tuple[str, str, str], SchemaColumn]:
        return {self._column_key(column): column for column in columns}

    def _diff_snapshots(
        self, previous: Optional[SchemaSnapshot], current: SchemaSnapshot
    ) -> SchemaDiff:
        current_index = self._to_index(current.columns)
        previous_index = self._to_index(previous.columns if previous else [])

        added = [c for k, c in current_index.items() if k not in previous_index]
        removed = [c for k, c in previous_index.items() if k not in current_index]

        changed: List[SchemaColumn] = []
        for key, current_col in current_index.items():
            old_col = previous_index.get(key)
            if old_col is None:
                continue
            if (
                old_col.data_type != current_col.data_type
                or old_col.is_nullable != current_col.is_nullable
            ):
                changed.append(current_col)

        return SchemaDiff(
            previous_schema_hash=previous.schema_hash if previous else None,
            current_schema_hash=current.schema_hash,
            added_columns=added,
            removed_columns=removed,
            changed_columns=changed,
        )

    async def _patch_memory_for_drift(
        self, context: ToolContext, diff: SchemaDiff
    ) -> None:
        summary = (
            f"Schema drift detected. Added: {len(diff.added_columns)}, "
            f"Removed: {len(diff.removed_columns)}, Changed: {len(diff.changed_columns)}. "
            f"Current schema hash: {diff.current_schema_hash}."
        )
        await context.agent_memory.save_text_memory(summary, context)

        for column in (diff.added_columns + diff.changed_columns)[:25]:
            await context.agent_memory.save_text_memory(
                (
                    f"Schema entity updated: "
                    f"{column.schema_name or 'default'}.{column.table_name}.{column.column_name} "
                    f"type={column.data_type} nullable={column.is_nullable}"
                ),
                context,
            )


def _cron_matches(expr: str, dt: datetime) -> bool:
    """Very small cron matcher for 5-field cron expressions."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError("cron_schedule must use 5 fields: m h dom mon dow")

    minute, hour, day_of_month, month, day_of_week = parts
    return all(
        [
            _field_matches(minute, dt.minute),
            _field_matches(hour, dt.hour),
            _field_matches(day_of_month, dt.day),
            _field_matches(month, dt.month),
            _field_matches(day_of_week, (dt.weekday() + 1) % 7),
        ]
    )


def _field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True

    if field.startswith("*/"):
        interval = int(field[2:])
        return value % interval == 0

    if "," in field:
        return any(_field_matches(part.strip(), value) for part in field.split(","))

    return int(field) == value
