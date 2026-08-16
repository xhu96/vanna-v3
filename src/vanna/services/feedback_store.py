"""Durable tenant-scoped feedback storage interfaces and SQLite default."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional

from .feedback_models import FeedbackRecord, MemoryPatchStatus, ReviewStatus


class FeedbackStoreError(RuntimeError):
    """Base error for durable feedback state operations."""


class FeedbackStateError(FeedbackStoreError):
    """Raised when a review transition is invalid or races another reviewer."""


class FeedbackStore(ABC):
    @abstractmethod
    def create(self, record: FeedbackRecord) -> None:
        """Persist one immutable feedback submission."""

    @abstractmethod
    def get(self, tenant_scope: str, feedback_id: str) -> Optional[FeedbackRecord]:
        """Get one record without crossing tenant scope."""

    @abstractmethod
    def record_memory_patch_attempt(
        self,
        tenant_scope: str,
        feedback_id: str,
        *,
        status: MemoryPatchStatus,
        patched_memories: int,
        error_code: Optional[str],
    ) -> FeedbackRecord:
        """Atomically record one idempotent memory-patch attempt."""

    @abstractmethod
    def list_for_review(
        self,
        tenant_scope: str,
        *,
        status: ReviewStatus = "pending",
        limit: int = 100,
    ) -> List[FeedbackRecord]:
        """List bounded review records in deterministic order."""

    @abstractmethod
    def transition_review(
        self,
        tenant_scope: str,
        feedback_id: str,
        *,
        status: ReviewStatus,
        reviewer_id: str,
        reviewer_note: Optional[str],
        reviewed_at: str,
    ) -> FeedbackRecord:
        """Transition only after its initial memory patch is durably applied."""

    @abstractmethod
    def record_review_memory_patch_attempt(
        self,
        tenant_scope: str,
        feedback_id: str,
        *,
        status: MemoryPatchStatus,
        error_code: Optional[str],
    ) -> FeedbackRecord:
        """Record application of one terminal review decision to memory."""

    @abstractmethod
    def list_approved(
        self,
        tenant_scope: str,
        *,
        limit: int = 100_000,
    ) -> List[FeedbackRecord]:
        """Return only approved records for offline training export."""


class SqliteFeedbackStore(FeedbackStore):
    """Transactional local default suitable for one host/process group."""

    def __init__(self, path: str = ".vanna/feedback.sqlite3") -> None:
        if path == ":memory:":
            raise ValueError("SqliteFeedbackStore requires a durable filesystem path")
        self.path = Path(path)
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(self.path.parent, 0o700)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        os.chmod(self.path, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_records (
                    feedback_id TEXT PRIMARY KEY,
                    tenant_scope TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                    question TEXT,
                    question_hash TEXT,
                    original_sql TEXT,
                    original_sql_hash TEXT,
                    corrected_sql TEXT,
                    corrected_sql_hash TEXT,
                    correction_validated INTEGER NOT NULL,
                    reason_codes_json TEXT NOT NULL,
                    user_edits TEXT,
                    conversation_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    planned_memory_patches INTEGER NOT NULL DEFAULT 0,
                    patched_memories INTEGER NOT NULL,
                    memory_patch_status TEXT NOT NULL DEFAULT 'applied',
                    memory_patch_attempts INTEGER NOT NULL DEFAULT 0,
                    memory_patch_error_code TEXT,
                    review_status TEXT CHECK (
                        review_status IS NULL OR
                        review_status IN ('pending', 'approved', 'rejected')
                    ),
                    reviewer_id TEXT,
                    reviewer_note TEXT,
                    reviewed_at TEXT,
                    review_memory_patch_status TEXT,
                    review_memory_patch_attempts INTEGER NOT NULL DEFAULT 0,
                    review_memory_patch_error_code TEXT
                )
                """
            )
            self._migrate_memory_patch_columns(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS feedback_review_scope_idx
                ON feedback_records (tenant_scope, review_status, created_at, feedback_id)
                """
            )

    def create(self, record: FeedbackRecord) -> None:
        values = self._record_values(record)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO feedback_records (
                    feedback_id, tenant_scope, user_id, rating, question,
                    question_hash, original_sql, original_sql_hash, corrected_sql,
                    corrected_sql_hash, correction_validated, reason_codes_json,
                    user_edits, conversation_id, request_id, created_at,
                    planned_memory_patches, patched_memories, memory_patch_status,
                    memory_patch_attempts, memory_patch_error_code, review_status,
                    reviewer_id, reviewer_note, reviewed_at,
                    review_memory_patch_status, review_memory_patch_attempts,
                    review_memory_patch_error_code
                ) VALUES (
                    :feedback_id, :tenant_scope, :user_id, :rating, :question,
                    :question_hash, :original_sql, :original_sql_hash, :corrected_sql,
                    :corrected_sql_hash, :correction_validated, :reason_codes_json,
                    :user_edits, :conversation_id, :request_id, :created_at,
                    :planned_memory_patches, :patched_memories,
                    :memory_patch_status, :memory_patch_attempts,
                    :memory_patch_error_code, :review_status, :reviewer_id,
                    :reviewer_note, :reviewed_at, :review_memory_patch_status,
                    :review_memory_patch_attempts, :review_memory_patch_error_code
                )
                """,
                values,
            )

    def get(self, tenant_scope: str, feedback_id: str) -> Optional[FeedbackRecord]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM feedback_records
                WHERE tenant_scope = ? AND feedback_id = ?
                """,
                (tenant_scope, feedback_id),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def record_memory_patch_attempt(
        self,
        tenant_scope: str,
        feedback_id: str,
        *,
        status: MemoryPatchStatus,
        patched_memories: int,
        error_code: Optional[str],
    ) -> FeedbackRecord:
        if status not in {"applied", "failed"}:
            raise FeedbackStateError("memory patch attempt must be applied or failed")
        if not 0 <= patched_memories <= 2:
            raise FeedbackStateError("patched memory count is invalid")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE feedback_records
                SET patched_memories = ?, memory_patch_status = ?,
                    memory_patch_attempts = memory_patch_attempts + 1,
                    memory_patch_error_code = ?
                WHERE tenant_scope = ? AND feedback_id = ?
                """,
                (
                    patched_memories,
                    status,
                    error_code,
                    tenant_scope,
                    feedback_id,
                ),
            )
            if cursor.rowcount != 1:
                raise FeedbackStateError("feedback memory patch record is missing")
            row = connection.execute(
                """
                SELECT * FROM feedback_records
                WHERE tenant_scope = ? AND feedback_id = ?
                """,
                (tenant_scope, feedback_id),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the transaction
            raise FeedbackStoreError("feedback memory patch record disappeared")
        return self._row_to_record(row)

    def list_for_review(
        self,
        tenant_scope: str,
        *,
        status: ReviewStatus = "pending",
        limit: int = 100,
    ) -> List[FeedbackRecord]:
        bounded_limit = min(max(limit, 1), 1000)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM feedback_records
                WHERE tenant_scope = ? AND review_status = ?
                    AND (
                        planned_memory_patches = 0 OR
                        (
                            memory_patch_status = 'applied' AND
                            patched_memories = planned_memory_patches
                        )
                    )
                ORDER BY created_at ASC, feedback_id ASC
                LIMIT ?
                """,
                (tenant_scope, status, bounded_limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def transition_review(
        self,
        tenant_scope: str,
        feedback_id: str,
        *,
        status: ReviewStatus,
        reviewer_id: str,
        reviewer_note: Optional[str],
        reviewed_at: str,
    ) -> FeedbackRecord:
        if status not in {"approved", "rejected"}:
            raise FeedbackStateError("review target must be approved or rejected")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE feedback_records
                SET review_status = ?, reviewer_id = ?, reviewer_note = ?, reviewed_at = ?,
                    review_memory_patch_status = CASE
                        WHEN planned_memory_patches > 0 THEN 'pending'
                        ELSE 'applied'
                    END,
                    review_memory_patch_error_code = NULL
                WHERE tenant_scope = ? AND feedback_id = ?
                    AND review_status = 'pending'
                    AND (
                        planned_memory_patches = 0 OR
                        (
                            memory_patch_status = 'applied' AND
                            patched_memories = planned_memory_patches
                        )
                    )
                """,
                (
                    status,
                    reviewer_id,
                    reviewer_note,
                    reviewed_at,
                    tenant_scope,
                    feedback_id,
                ),
            )
            if cursor.rowcount != 1:
                blocked = connection.execute(
                    """
                    SELECT planned_memory_patches, patched_memories,
                        memory_patch_status, review_status
                    FROM feedback_records
                    WHERE tenant_scope = ? AND feedback_id = ?
                    """,
                    (tenant_scope, feedback_id),
                ).fetchone()
                if (
                    blocked is not None
                    and blocked["review_status"] == "pending"
                    and blocked["planned_memory_patches"] > 0
                    and (
                        blocked["memory_patch_status"] != "applied"
                        or blocked["patched_memories"]
                        != blocked["planned_memory_patches"]
                    )
                ):
                    raise FeedbackStateError(
                        "feedback memory patch must be applied before review"
                    )
                raise FeedbackStateError(
                    "feedback record is missing, outside scope, or no longer pending"
                )
            row = connection.execute(
                """
                SELECT * FROM feedback_records
                WHERE tenant_scope = ? AND feedback_id = ?
                """,
                (tenant_scope, feedback_id),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the transaction
            raise FeedbackStoreError("reviewed feedback disappeared")
        return self._row_to_record(row)

    def record_review_memory_patch_attempt(
        self,
        tenant_scope: str,
        feedback_id: str,
        *,
        status: MemoryPatchStatus,
        error_code: Optional[str],
    ) -> FeedbackRecord:
        if status not in {"applied", "failed"}:
            raise FeedbackStateError(
                "review memory patch attempt must be applied or failed"
            )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE feedback_records
                SET review_memory_patch_status = ?,
                    review_memory_patch_attempts = review_memory_patch_attempts + 1,
                    review_memory_patch_error_code = ?
                WHERE tenant_scope = ? AND feedback_id = ?
                    AND review_status IN ('approved', 'rejected')
                """,
                (status, error_code, tenant_scope, feedback_id),
            )
            if cursor.rowcount != 1:
                raise FeedbackStateError(
                    "reviewed feedback memory patch record is missing"
                )
            row = connection.execute(
                """
                SELECT * FROM feedback_records
                WHERE tenant_scope = ? AND feedback_id = ?
                """,
                (tenant_scope, feedback_id),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the transaction
            raise FeedbackStoreError("reviewed feedback disappeared")
        return self._row_to_record(row)

    def list_approved(
        self,
        tenant_scope: str,
        *,
        limit: int = 100_000,
    ) -> List[FeedbackRecord]:
        bounded_limit = min(max(limit, 1), 100_000)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM feedback_records
                WHERE tenant_scope = ? AND review_status = 'approved'
                    AND (
                        planned_memory_patches = 0 OR
                        review_memory_patch_status = 'applied'
                    )
                ORDER BY reviewed_at ASC, feedback_id ASC
                LIMIT ?
                """,
                (tenant_scope, bounded_limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _record_values(record: FeedbackRecord) -> dict[str, Any]:
        values = record.model_dump(mode="json")
        values["reason_codes_json"] = json.dumps(
            values.pop("reason_codes"),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        values["correction_validated"] = int(record.correction_validated)
        return values

    @staticmethod
    def _migrate_memory_patch_columns(connection: sqlite3.Connection) -> None:
        existing = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(feedback_records)")
        }
        columns = {
            "planned_memory_patches": "INTEGER NOT NULL DEFAULT 0",
            "memory_patch_status": "TEXT NOT NULL DEFAULT 'applied'",
            "memory_patch_attempts": "INTEGER NOT NULL DEFAULT 0",
            "memory_patch_error_code": "TEXT",
            "review_memory_patch_status": "TEXT",
            "review_memory_patch_attempts": "INTEGER NOT NULL DEFAULT 0",
            "review_memory_patch_error_code": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE feedback_records ADD COLUMN {name} {definition}"
                )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> FeedbackRecord:
        values = dict(row)
        values["reason_codes"] = json.loads(values.pop("reason_codes_json"))
        values["correction_validated"] = bool(values["correction_validated"])
        return FeedbackRecord.model_validate(values)


__all__ = [
    "FeedbackStateError",
    "FeedbackStore",
    "FeedbackStoreError",
    "SqliteFeedbackStore",
]
