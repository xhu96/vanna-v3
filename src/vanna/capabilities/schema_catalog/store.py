"""Transactional local storage for immutable schema snapshots."""

from __future__ import annotations

import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from .models import SchemaMemoryPatch, SchemaSnapshot, normalize_scope_id, utc_now

PatchFactory = Callable[
    [Optional[SchemaSnapshot], SchemaSnapshot], Sequence[SchemaMemoryPatch]
]


@dataclass(frozen=True)
class SnapshotWriteOutcome:
    """Atomic compare-and-persist result."""

    previous: Optional[SchemaSnapshot]
    snapshot: SchemaSnapshot
    created: bool


@dataclass(frozen=True)
class PatchClaim:
    """Exclusive, expiring claim over pending memory patches."""

    claim_token: str
    patches: List[SchemaMemoryPatch]


class SchemaSnapshotStore(ABC):
    """Storage contract for tenant-isolated immutable snapshots."""

    @abstractmethod
    def get_latest(self, tenant_id: str) -> Optional[SchemaSnapshot]:
        pass

    @abstractmethod
    def get_snapshot(
        self, tenant_id: str, snapshot_id: str
    ) -> Optional[SchemaSnapshot]:
        pass

    @abstractmethod
    def list_snapshots(self, tenant_id: str, limit: int = 50) -> List[SchemaSnapshot]:
        pass

    @abstractmethod
    def write_snapshot(
        self,
        candidate: SchemaSnapshot,
        patch_factory: Optional[PatchFactory] = None,
    ) -> SnapshotWriteOutcome:
        pass

    @abstractmethod
    def claim_pending_patches(self, tenant_id: str, limit: int = 1000) -> PatchClaim:
        pass

    @abstractmethod
    def count_pending_patches(self, tenant_id: str) -> int:
        pass

    @abstractmethod
    def mark_patch_applied(
        self, tenant_id: str, patch_id: str, claim_token: str
    ) -> None:
        pass

    @abstractmethod
    def release_patch_claim(self, tenant_id: str, claim_token: str) -> None:
        pass

    @abstractmethod
    def claim_schedule(self, tenant_id: str, schedule_key: str) -> bool:
        pass

    @abstractmethod
    def release_schedule(self, tenant_id: str, schedule_key: str) -> None:
        pass


class SqliteSchemaSnapshotStore(SchemaSnapshotStore):
    """SQLite-backed store with atomic versions and a durable patch outbox."""

    _FORMAT_VERSION = 1

    def __init__(self, path: str = ".vanna/schema_catalog.sqlite3") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self._reject_legacy_json()
        self._initialize()

    def _reject_legacy_json(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("rb") as handle:
            header = handle.read(16)
        if header != b"SQLite format 3\x00":
            raise ValueError(
                "Schema catalog path contains the legacy JSON format. Configure a "
                "new .sqlite3 path or migrate it with an explicit tenant mapping."
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schema_snapshots (
                    tenant_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
                    schema_hash TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, snapshot_id),
                    UNIQUE (tenant_id, schema_version)
                );
                CREATE TABLE IF NOT EXISTS schema_tenant_state (
                    tenant_id TEXT PRIMARY KEY,
                    latest_snapshot_id TEXT NOT NULL,
                    latest_schema_version INTEGER NOT NULL,
                    latest_schema_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schema_memory_patch_outbox (
                    tenant_id TEXT NOT NULL,
                    patch_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    applied_at TEXT,
                    claim_token TEXT,
                    claimed_at TEXT,
                    PRIMARY KEY (tenant_id, patch_id)
                );
                CREATE TABLE IF NOT EXISTS schema_schedule_claims (
                    tenant_id TEXT NOT NULL,
                    schedule_key TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, schedule_key)
                );
                CREATE TRIGGER IF NOT EXISTS schema_snapshots_no_update
                BEFORE UPDATE ON schema_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'schema snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS schema_snapshots_no_delete
                BEFORE DELETE ON schema_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'schema snapshots are immutable');
                END;
                """
            )
            existing = connection.execute(
                "SELECT value FROM schema_store_meta WHERE key='format_version'"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO schema_store_meta(key, value) VALUES (?, ?)",
                    ("format_version", str(self._FORMAT_VERSION)),
                )
            elif existing["value"] != str(self._FORMAT_VERSION):
                raise ValueError("Unsupported schema snapshot store format")
        finally:
            connection.close()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def count_pending_patches(self, tenant_id: str) -> int:
        tenant_id = normalize_scope_id(tenant_id)
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM schema_memory_patch_outbox
                WHERE tenant_id = ? AND applied_at IS NULL
                """,
                (tenant_id,),
            ).fetchone()
            return int(row["count"])
        finally:
            connection.close()

    @staticmethod
    def _snapshot_from_row(row: Optional[sqlite3.Row]) -> Optional[SchemaSnapshot]:
        if row is None:
            return None
        return SchemaSnapshot.model_validate_json(row["payload"])

    @classmethod
    def _latest_on_connection(
        cls, connection: sqlite3.Connection, tenant_id: str
    ) -> Optional[SchemaSnapshot]:
        row = connection.execute(
            """
            SELECT s.payload
            FROM schema_tenant_state AS state
            JOIN schema_snapshots AS s
              ON s.tenant_id = state.tenant_id
             AND s.snapshot_id = state.latest_snapshot_id
            WHERE state.tenant_id = ?
            """,
            (tenant_id,),
        ).fetchone()
        return cls._snapshot_from_row(row)

    def get_latest(self, tenant_id: str) -> Optional[SchemaSnapshot]:
        tenant_id = normalize_scope_id(tenant_id)
        connection = self._connect()
        try:
            return self._latest_on_connection(connection, tenant_id)
        finally:
            connection.close()

    def get_snapshot(
        self, tenant_id: str, snapshot_id: str
    ) -> Optional[SchemaSnapshot]:
        tenant_id = normalize_scope_id(tenant_id)
        snapshot_id = normalize_scope_id(snapshot_id, "snapshot_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT payload FROM schema_snapshots "
                "WHERE tenant_id = ? AND snapshot_id = ?",
                (tenant_id, snapshot_id),
            ).fetchone()
            return self._snapshot_from_row(row)
        finally:
            connection.close()

    def list_snapshots(self, tenant_id: str, limit: int = 50) -> List[SchemaSnapshot]:
        tenant_id = normalize_scope_id(tenant_id)
        if not 1 <= limit <= 1000:
            raise ValueError("snapshot history limit must be between 1 and 1000")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT payload FROM schema_snapshots WHERE tenant_id = ? "
                "ORDER BY schema_version DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
            return [SchemaSnapshot.model_validate_json(row["payload"]) for row in rows]
        finally:
            connection.close()

    def write_snapshot(
        self,
        candidate: SchemaSnapshot,
        patch_factory: Optional[PatchFactory] = None,
    ) -> SnapshotWriteOutcome:
        tenant_id = normalize_scope_id(candidate.tenant_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._latest_on_connection(connection, tenant_id)
            if previous is not None and previous.schema_hash == candidate.schema_hash:
                connection.execute("COMMIT")
                return SnapshotWriteOutcome(
                    previous=previous,
                    snapshot=previous,
                    created=False,
                )

            schema_version = 1 if previous is None else previous.schema_version + 1
            snapshot_id = (
                f"snap_{schema_version:08d}_{candidate.schema_hash[:16]}_"
                f"{uuid.uuid4().hex[:12]}"
            )
            snapshot_payload = candidate.model_dump()
            snapshot_payload.update(
                {
                    "snapshot_id": snapshot_id,
                    "schema_version": schema_version,
                    "previous_snapshot_id": (
                        previous.snapshot_id if previous is not None else None
                    ),
                }
            )
            snapshot = SchemaSnapshot.model_validate(snapshot_payload)
            payload = snapshot.model_dump_json()
            connection.execute(
                """
                INSERT INTO schema_snapshots(
                    tenant_id, snapshot_id, schema_version, schema_hash,
                    captured_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    snapshot.snapshot_id,
                    snapshot.schema_version,
                    snapshot.schema_hash,
                    snapshot.captured_at.isoformat(),
                    payload,
                ),
            )
            connection.execute(
                """
                INSERT INTO schema_tenant_state(
                    tenant_id, latest_snapshot_id, latest_schema_version,
                    latest_schema_hash
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    latest_snapshot_id=excluded.latest_snapshot_id,
                    latest_schema_version=excluded.latest_schema_version,
                    latest_schema_hash=excluded.latest_schema_hash
                """,
                (
                    tenant_id,
                    snapshot.snapshot_id,
                    snapshot.schema_version,
                    snapshot.schema_hash,
                ),
            )

            patches = list(patch_factory(previous, snapshot)) if patch_factory else []
            for patch in patches:
                if (
                    patch.tenant_id != tenant_id
                    or patch.snapshot_id != snapshot.snapshot_id
                    or patch.schema_version != snapshot.schema_version
                ):
                    raise ValueError("schema memory patch provenance does not match")
                connection.execute(
                    """
                    INSERT INTO schema_memory_patch_outbox(
                        tenant_id, patch_id, snapshot_id, payload, applied_at
                    ) VALUES (?, ?, ?, ?, NULL)
                    """,
                    (
                        tenant_id,
                        patch.patch_id,
                        snapshot.snapshot_id,
                        patch.model_dump_json(),
                    ),
                )
            connection.execute("COMMIT")
            return SnapshotWriteOutcome(
                previous=previous,
                snapshot=snapshot,
                created=True,
            )
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def claim_pending_patches(self, tenant_id: str, limit: int = 1000) -> PatchClaim:
        tenant_id = normalize_scope_id(tenant_id)
        if not 1 <= limit <= 10_000:
            raise ValueError("pending patch limit must be between 1 and 10000")
        claim_token = f"claim_{uuid.uuid4().hex}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            stale_before = (utc_now() - timedelta(minutes=5)).isoformat()
            connection.execute(
                """
                UPDATE schema_memory_patch_outbox
                SET claim_token = NULL, claimed_at = NULL
                WHERE tenant_id = ? AND applied_at IS NULL
                  AND claimed_at IS NOT NULL AND claimed_at < ?
                """,
                (tenant_id, stale_before),
            )
            rows = connection.execute(
                """
                SELECT rowid, payload FROM schema_memory_patch_outbox
                WHERE tenant_id = ? AND applied_at IS NULL AND claim_token IS NULL
                ORDER BY rowid ASC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
            if rows:
                row_ids = [int(row["rowid"]) for row in rows]
                placeholders = ",".join("?" for _ in row_ids)
                connection.execute(
                    f"""
                    UPDATE schema_memory_patch_outbox
                    SET claim_token = ?, claimed_at = ?
                    WHERE rowid IN ({placeholders})
                    """,
                    (claim_token, utc_now().isoformat(), *row_ids),
                )
            connection.execute("COMMIT")
            return PatchClaim(
                claim_token=claim_token,
                patches=[
                    SchemaMemoryPatch.model_validate_json(row["payload"])
                    for row in rows
                ],
            )
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def mark_patch_applied(
        self, tenant_id: str, patch_id: str, claim_token: str
    ) -> None:
        tenant_id = normalize_scope_id(tenant_id)
        patch_id = normalize_scope_id(patch_id, "patch_id")
        claim_token = normalize_scope_id(claim_token, "claim_token")
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE schema_memory_patch_outbox
                SET applied_at = ?
                WHERE tenant_id = ? AND patch_id = ? AND applied_at IS NULL
                  AND claim_token = ?
                """,
                (utc_now().isoformat(), tenant_id, patch_id, claim_token),
            )
            if cursor.rowcount != 1:
                raise ValueError("schema memory patch claim is no longer valid")
        finally:
            connection.close()

    def release_patch_claim(self, tenant_id: str, claim_token: str) -> None:
        tenant_id = normalize_scope_id(tenant_id)
        claim_token = normalize_scope_id(claim_token, "claim_token")
        connection = self._connect()
        try:
            connection.execute(
                """
                UPDATE schema_memory_patch_outbox
                SET claim_token = NULL, claimed_at = NULL
                WHERE tenant_id = ? AND claim_token = ? AND applied_at IS NULL
                """,
                (tenant_id, claim_token),
            )
        finally:
            connection.close()

    def claim_schedule(self, tenant_id: str, schedule_key: str) -> bool:
        tenant_id = normalize_scope_id(tenant_id)
        schedule_key = normalize_scope_id(schedule_key, "schedule_key")
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO schema_schedule_claims(
                    tenant_id, schedule_key, claimed_at
                ) VALUES (?, ?, ?)
                """,
                (tenant_id, schedule_key, utc_now().isoformat()),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def release_schedule(self, tenant_id: str, schedule_key: str) -> None:
        tenant_id = normalize_scope_id(tenant_id)
        schedule_key = normalize_scope_id(schedule_key, "schedule_key")
        connection = self._connect()
        try:
            connection.execute(
                "DELETE FROM schema_schedule_claims "
                "WHERE tenant_id = ? AND schedule_key = ?",
                (tenant_id, schedule_key),
            )
        finally:
            connection.close()


__all__ = [
    "PatchFactory",
    "PatchClaim",
    "SchemaSnapshotStore",
    "SnapshotWriteOutcome",
    "SqliteSchemaSnapshotStore",
]
