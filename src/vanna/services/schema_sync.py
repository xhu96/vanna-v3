"""Portable tenant-scoped schema snapshot and drift synchronization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Collection, Dict, Iterable, List, Optional, Sequence, Tuple

from vanna.capabilities.schema_catalog import (
    SchemaCatalog,
    SchemaCatalogAdapter,
    SchemaColumn,
    SchemaDiff,
    SchemaMemoryPatch,
    SchemaSnapshot,
    SchemaSnapshotStore,
    SchemaSyncResult,
    SqliteSchemaSnapshotStore,
    canonical_schema_hash,
)
from vanna.capabilities.sql_runner import SqlRunner
from vanna.core.tool import ToolContext
from vanna.integrations.schema_catalog import (
    InformationSchemaCatalogAdapter,
    SqliteCatalogAdapter,
)
from vanna.security.sql_policy import normalize_sql_dialect

TenantResolver = Callable[[ToolContext], str]
Clock = Callable[[], datetime]


class SchemaScopeError(ValueError):
    """Raised when an authenticated storage scope cannot be established."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def authenticated_tenant_scope(context: ToolContext) -> str:
    """Resolve tenant only from trusted user identity, never request metadata."""

    from vanna.capabilities.schema_catalog.models import normalize_scope_id

    if not context.user.authenticated:
        raise SchemaScopeError("Schema synchronization requires authentication")
    claimed_tenant = context.user.metadata.get("tenant_id")
    if claimed_tenant is None:
        claimed_tenant = f"user:{context.user.id}"
    if not isinstance(claimed_tenant, str):
        raise SchemaScopeError("Trusted tenant claim must be a string")
    try:
        return normalize_scope_id(claimed_tenant)
    except ValueError:
        raise SchemaScopeError("Trusted tenant claim is invalid") from None


class PortableSchemaCatalogService(SchemaCatalog):
    """Portable catalogs, immutable snapshots, drift, and memory patching."""

    def __init__(
        self,
        sql_runner: SqlRunner,
        *,
        persist_path: str = ".vanna/schema_catalog.sqlite3",
        dialect: Optional[str] = None,
        cron_schedule: Optional[str] = None,
        catalog_adapter: Optional[SchemaCatalogAdapter] = None,
        snapshot_store: Optional[SchemaSnapshotStore] = None,
        tenant_resolver: TenantResolver = authenticated_tenant_scope,
        memory_patch_batch_size: int = 1000,
        apply_memory_patches: bool = True,
        require_native_read_only: bool = True,
        catalog_schemas: Optional[Collection[str]] = None,
        catalog_tables: Optional[Collection[str]] = None,
        require_catalog_scope: bool = True,
        clock: Clock = _utc_now,
    ) -> None:
        self.sql_runner = sql_runner
        reported = getattr(sql_runner, "dialect", "unknown")
        runner_dialect = normalize_sql_dialect(
            reported if isinstance(reported, str) else "unknown"
        )
        explicit_dialect = (
            normalize_sql_dialect(dialect) if dialect is not None else None
        )
        if (
            explicit_dialect is not None
            and runner_dialect != "unknown"
            and explicit_dialect != runner_dialect
        ):
            raise ValueError("Schema service dialect does not match the SQL runner")

        adapter_dialect = normalize_sql_dialect(
            str(getattr(catalog_adapter, "dialect", "unknown"))
        )
        self.dialect = explicit_dialect or (
            runner_dialect if runner_dialect != "unknown" else adapter_dialect
        )
        if self.dialect == "unknown":
            raise ValueError(
                "Schema synchronization requires SqlRunner.dialect or dialect=..."
            )
        if adapter_dialect != "unknown" and adapter_dialect != self.dialect:
            raise ValueError("Schema catalog adapter dialect does not match the runner")

        if catalog_adapter is None:
            if self.dialect == "sqlite":
                catalog_adapter = SqliteCatalogAdapter(
                    sql_runner,
                    catalog_tables=catalog_tables,
                    require_catalog_scope=require_catalog_scope,
                    require_native_read_only=require_native_read_only,
                )
            else:
                catalog_adapter = InformationSchemaCatalogAdapter(
                    sql_runner,
                    dialect=self.dialect,
                    catalog_schemas=catalog_schemas,
                    require_catalog_scope=require_catalog_scope,
                    require_native_read_only=require_native_read_only,
                )
        self.catalog_adapter = catalog_adapter
        self.snapshot_store = snapshot_store or SqliteSchemaSnapshotStore(persist_path)
        self.tenant_resolver = tenant_resolver
        if not 1 <= memory_patch_batch_size <= 10_000:
            raise ValueError("memory_patch_batch_size must be between 1 and 10000")
        self.memory_patch_batch_size = memory_patch_batch_size
        self.apply_memory_patches = apply_memory_patches
        self.clock = clock
        self.cron_schedule = cron_schedule.strip() if cron_schedule else None
        if self.cron_schedule is not None:
            _validate_cron(self.cron_schedule)

    def _tenant_id(self, context: ToolContext) -> str:
        try:
            tenant_id = self.tenant_resolver(context)
        except SchemaScopeError:
            raise
        except Exception:
            raise SchemaScopeError("Tenant scope resolution failed") from None
        if not isinstance(tenant_id, str):
            raise SchemaScopeError("Tenant scope resolution returned an invalid value")
        from vanna.capabilities.schema_catalog.models import normalize_scope_id

        try:
            return normalize_scope_id(tenant_id)
        except ValueError:
            raise SchemaScopeError(
                "Tenant scope resolution returned an invalid value"
            ) from None

    def _captured_at(self) -> datetime:
        captured = self.clock()
        if captured.tzinfo is None or captured.utcoffset() is None:
            captured = captured.replace(tzinfo=timezone.utc)
        return captured.astimezone(timezone.utc)

    async def capture_snapshot(self, context: ToolContext) -> SchemaSnapshot:
        tenant_id = self._tenant_id(context)
        columns = await self.catalog_adapter.fetch_columns(context)
        schema_hash = self.compute_hash(columns)
        latest = await asyncio.to_thread(self.snapshot_store.get_latest, tenant_id)
        return SchemaSnapshot(
            snapshot_id=f"capture_{schema_hash[:16]}_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            schema_version=1 if latest is None else latest.schema_version + 1,
            captured_at=self._captured_at(),
            dialect=self.dialect,
            schema_hash=schema_hash,
            previous_snapshot_id=latest.snapshot_id if latest is not None else None,
            columns=columns,
        )

    async def sync(self, context: ToolContext) -> SchemaSyncResult:
        candidate = await self.capture_snapshot(context)
        outcome = await asyncio.to_thread(
            self.snapshot_store.write_snapshot,
            candidate,
            self._build_memory_patches,
        )
        previous = outcome.previous if outcome.created else outcome.snapshot
        diff = self.diff_snapshots(previous, outcome.snapshot)
        applied = (
            await self._drain_memory_patch_outbox(
                context,
                outcome.snapshot.tenant_id,
            )
            if self.apply_memory_patches
            else []
        )
        pending = await asyncio.to_thread(
            self.snapshot_store.count_pending_patches,
            outcome.snapshot.tenant_id,
        )
        return SchemaSyncResult(
            snapshot=outcome.snapshot,
            diff=diff,
            persisted=outcome.created,
            memory_patches_applied=applied,
            memory_patches_pending=pending,
        )

    async def get_latest_snapshot(
        self, context: ToolContext
    ) -> Optional[SchemaSnapshot]:
        return await asyncio.to_thread(
            self.snapshot_store.get_latest,
            self._tenant_id(context),
        )

    async def get_snapshot(
        self,
        context: ToolContext,
        snapshot_id: str,
    ) -> Optional[SchemaSnapshot]:
        return await asyncio.to_thread(
            self.snapshot_store.get_snapshot,
            self._tenant_id(context),
            snapshot_id,
        )

    async def list_snapshot_history(
        self,
        context: ToolContext,
        *,
        limit: int = 50,
    ) -> List[SchemaSnapshot]:
        return await asyncio.to_thread(
            self.snapshot_store.list_snapshots,
            self._tenant_id(context),
            limit,
        )

    async def get_lineage_metadata(self, context: ToolContext) -> Dict[str, object]:
        latest = await self.get_latest_snapshot(context)
        if latest is None:
            return {}
        return {
            "schema_hash": latest.schema_hash,
            "schema_version": latest.schema_version,
            "schema_snapshot_id": latest.snapshot_id,
            "schema_drift_detected": latest.previous_snapshot_id is not None,
            "schema_captured_at": latest.captured_at.isoformat(),
        }

    async def run_scheduled_sync_if_due(
        self,
        context: ToolContext,
        now: Optional[datetime] = None,
    ) -> Optional[SchemaSyncResult]:
        """Run at most once per tenant and matching UTC cron minute."""

        if self.cron_schedule is None:
            return None
        current = now or self._captured_at()
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        if not _cron_matches(self.cron_schedule, current):
            return None

        tenant_id = self._tenant_id(context)
        schedule_digest = hashlib.sha256(
            self.cron_schedule.encode("utf-8")
        ).hexdigest()[:12]
        schedule_key = f"cron_{schedule_digest}_{current.strftime('%Y%m%dT%H%M')}"
        claimed = await asyncio.to_thread(
            self.snapshot_store.claim_schedule,
            tenant_id,
            schedule_key,
        )
        if not claimed:
            return None
        try:
            return await self.sync(context)
        except Exception:
            await asyncio.to_thread(
                self.snapshot_store.release_schedule,
                tenant_id,
                schedule_key,
            )
            raise

    @staticmethod
    def compute_hash(columns: Sequence[SchemaColumn]) -> str:
        return canonical_schema_hash(columns)

    @staticmethod
    def _column_key(column: SchemaColumn) -> Tuple[str, str, str]:
        return (column.schema_name or "", column.table_name, column.column_name)

    @classmethod
    def _to_index(
        cls, columns: Iterable[SchemaColumn]
    ) -> Dict[Tuple[str, str, str], SchemaColumn]:
        return {cls._column_key(column): column for column in columns}

    @classmethod
    def diff_snapshots(
        cls,
        previous: Optional[SchemaSnapshot],
        current: SchemaSnapshot,
    ) -> SchemaDiff:
        current_index = cls._to_index(current.columns)
        previous_index = cls._to_index(previous.columns if previous else [])
        added = [
            column for key, column in current_index.items() if key not in previous_index
        ]
        removed = [
            column for key, column in previous_index.items() if key not in current_index
        ]
        changed = [
            current_column
            for key, current_column in current_index.items()
            if key in previous_index
            and (
                previous_index[key].data_type != current_column.data_type
                or previous_index[key].is_nullable != current_column.is_nullable
                or previous_index[key].ordinal_position
                != current_column.ordinal_position
            )
        ]
        added.sort(key=cls._column_key)
        removed.sort(key=cls._column_key)
        changed.sort(key=cls._column_key)
        return SchemaDiff(
            previous_schema_hash=previous.schema_hash if previous else None,
            current_schema_hash=current.schema_hash,
            previous_schema_version=previous.schema_version if previous else None,
            current_schema_version=current.schema_version,
            previous_snapshot_id=previous.snapshot_id if previous else None,
            current_snapshot_id=current.snapshot_id,
            added_columns=added,
            removed_columns=removed,
            changed_columns=changed,
            added_entities=[column.entity_id for column in added],
            removed_entities=[column.entity_id for column in removed],
            changed_entities=[column.entity_id for column in changed],
        )

    def _build_memory_patches(
        self,
        previous: Optional[SchemaSnapshot],
        current: SchemaSnapshot,
    ) -> Sequence[SchemaMemoryPatch]:
        diff = self.diff_snapshots(previous, current)
        if not diff.has_drift:
            return []

        descriptors: List[Tuple[str, str, Optional[SchemaColumn]]] = [
            ("summary", "schema", None)
        ]
        descriptors.extend(
            ("upsert", column.entity_id, column) for column in diff.added_columns
        )
        descriptors.extend(
            ("upsert", column.entity_id, column) for column in diff.changed_columns
        )
        descriptors.extend(
            ("tombstone", column.entity_id, column) for column in diff.removed_columns
        )

        patches: List[SchemaMemoryPatch] = []
        for action, entity_id, column in descriptors:
            patch_digest = hashlib.sha256(
                f"{current.snapshot_id}\0{action}\0{entity_id}".encode("utf-8")
            ).hexdigest()[:24]
            patch_id = f"schema_patch_{patch_digest}"
            payload: Dict[str, object] = {
                "kind": "schema_memory_patch",
                "format_version": 1,
                "patch_id": patch_id,
                "action": action,
                "entity_id": entity_id,
                "tenant_id": current.tenant_id,
                "snapshot_id": current.snapshot_id,
                "schema_version": current.schema_version,
                "schema_hash": current.schema_hash,
                "provenance": "schema_catalog_drift",
                "weight": 2.0,
            }
            if column is None:
                payload["drift_counts"] = {
                    "added": len(diff.added_columns),
                    "removed": len(diff.removed_columns),
                    "changed": len(diff.changed_columns),
                }
            else:
                payload["column"] = column.model_dump(mode="json")
            patches.append(
                SchemaMemoryPatch(
                    patch_id=patch_id,
                    tenant_id=current.tenant_id,
                    snapshot_id=current.snapshot_id,
                    schema_version=current.schema_version,
                    schema_hash=current.schema_hash,
                    action=action,  # type: ignore[arg-type]
                    entity_id=entity_id,
                    content=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
        return patches

    async def _drain_memory_patch_outbox(
        self,
        context: ToolContext,
        tenant_id: str,
    ) -> List[str]:
        if not context.agent_memory.supports_keyed_text_memory_upsert:
            pending = await asyncio.to_thread(
                self.snapshot_store.count_pending_patches,
                tenant_id,
            )
            if pending:
                raise RuntimeError(
                    "Schema memory synchronization requires a backend with "
                    "tenant-scoped keyed text-memory upsert support."
                )
            return []
        applied: List[str] = []
        while True:
            claim = await asyncio.to_thread(
                self.snapshot_store.claim_pending_patches,
                tenant_id,
                self.memory_patch_batch_size,
            )
            if not claim.patches:
                return applied
            try:
                for patch in claim.patches:
                    await context.agent_memory.upsert_text_memory(
                        patch.content,
                        context,
                        memory_key=f"schema:{patch.entity_id}",
                    )
                    await asyncio.to_thread(
                        self.snapshot_store.mark_patch_applied,
                        tenant_id,
                        patch.patch_id,
                        claim.claim_token,
                    )
                    applied.append(patch.patch_id)
            except Exception:
                await asyncio.to_thread(
                    self.snapshot_store.release_patch_claim,
                    tenant_id,
                    claim.claim_token,
                )
                raise


def _validate_cron(expr: str) -> None:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError("cron_schedule must use 5 fields: m h dom mon dow")
    bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    for field, (minimum, maximum) in zip(parts, bounds):
        _field_values(field, minimum, maximum)


def _cron_matches(expr: str, dt: datetime) -> bool:
    parts = expr.strip().split()
    _validate_cron(expr)
    minute, hour, day_of_month, month, day_of_week = parts
    if dt.minute not in _field_values(minute, 0, 59):
        return False
    if dt.hour not in _field_values(hour, 0, 23):
        return False
    if dt.month not in _field_values(month, 1, 12):
        return False

    dom_matches = dt.day in _field_values(day_of_month, 1, 31)
    cron_weekday = (dt.weekday() + 1) % 7
    dow_values = {value % 7 for value in _field_values(day_of_week, 0, 7)}
    dow_matches = cron_weekday in dow_values
    dom_wildcard = day_of_month == "*"
    dow_wildcard = day_of_week == "*"
    if dom_wildcard and dow_wildcard:
        return True
    if dom_wildcard:
        return dow_matches
    if dow_wildcard:
        return dom_matches
    return dom_matches or dow_matches


def _field_values(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for raw_item in field.split(","):
        item = raw_item.strip()
        if not item:
            raise ValueError("cron field contains an empty item")
        base, separator, raw_step = item.partition("/")
        if separator:
            if not raw_step.isdigit() or int(raw_step) <= 0:
                raise ValueError("cron step must be a positive integer")
            step = int(raw_step)
            if base != "*" and "-" not in base:
                raise ValueError("cron steps require '*' or a range")
        else:
            step = 1

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            if not raw_start.isdigit() or not raw_end.isdigit():
                raise ValueError("cron ranges must contain integers")
            start, end = int(raw_start), int(raw_end)
            if start > end:
                raise ValueError("cron ranges must be ascending")
        else:
            if not base.isdigit():
                raise ValueError("cron fields must contain integers")
            start = end = int(base)

        if start < minimum or end > maximum:
            raise ValueError("cron field value is outside its valid range")
        values.update(range(start, end + 1, step))
    return values


__all__ = [
    "PortableSchemaCatalogService",
    "SchemaScopeError",
    "authenticated_tenant_scope",
]
