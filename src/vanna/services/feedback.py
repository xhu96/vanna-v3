"""Tenant-scoped feedback, immediate memory patching, and review workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar

import sqlglot

from vanna.capabilities.agent_memory import memory_scope_for_context
from vanna.core.tool import ToolContext
from vanna.security.sql_policy import SqlQueryPolicy

from .feedback_models import (
    FeedbackRecord,
    FeedbackRequest,
    FeedbackResult,
    FeedbackReviewQueue,
    FeedbackReviewRequest,
    FeedbackReviewResult,
    ReviewStatus,
    TrainingExport,
    TrainingExportManifest,
)
from .feedback_store import FeedbackStateError, FeedbackStore, SqliteFeedbackStore

MAX_APPROVED_EXPORT_RECORDS = 250
MAX_APPROVED_EXPORT_BYTES = 64 * 1024 * 1024
_StoreResult = TypeVar("_StoreResult")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_question(value: Optional[str]) -> Optional[str]:
    return " ".join(value.casefold().split()) if value else None


def _atomic_write_private(path: Path, content: bytes) -> None:
    """Publish one owner-only file atomically and durably in its destination dir."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _generation_path(destination: Path, content_sha256: str) -> Path:
    directory = destination.parent / f".{destination.name}.generations"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    return directory / f"{content_sha256}.jsonl"


class FeedbackService:
    """Validate feedback, persist provenance, and patch memory immediately."""

    def __init__(
        self,
        *,
        store: Optional[FeedbackStore] = None,
        database_path: str = ".vanna/feedback.sqlite3",
        query_policy: Optional[SqlQueryPolicy] = None,
        sql_dialect: str = "postgres",
        feedback_log_path: Optional[str] = None,
        review_queue_path: Optional[str] = None,
    ) -> None:
        if feedback_log_path is not None or review_queue_path is not None:
            warnings.warn(
                "feedback_log_path/review_queue_path are deprecated; feedback is now "
                "stored transactionally in SQLite",
                DeprecationWarning,
                stacklevel=2,
            )
            legacy_path = feedback_log_path or review_queue_path
            if legacy_path and database_path == ".vanna/feedback.sqlite3":
                database_path = str(Path(legacy_path).with_suffix(".sqlite3"))
        self.store = store or SqliteFeedbackStore(database_path)
        self.query_policy = query_policy or SqlQueryPolicy(sql_dialect)

    @staticmethod
    async def _store_call(
        operation: Callable[..., _StoreResult],
        *args: object,
        **kwargs: object,
    ) -> _StoreResult:
        """Keep synchronous enterprise/local stores off the server event loop."""

        return await asyncio.to_thread(operation, *args, **kwargs)

    async def process_feedback(
        self,
        request: FeedbackRequest,
        context: ToolContext,
    ) -> FeedbackResult:
        if not context.user.authenticated:
            raise PermissionError("authenticated feedback is required")
        self._validate_request_identity(request, context)

        feedback_id = f"fb_{uuid.uuid4().hex}"
        now = _utc_now()
        tenant_scope = memory_scope_for_context(context)
        question_normalized = _normalize_question(request.question)
        original_sql = self._normalize_untrusted_sql(request.original_sql)
        corrected_sql = self._validate_correction(request.corrected_sql, context)
        planned_patches = int(
            request.rating == "down"
            and original_sql is not None
            and request.question is not None
        ) + int(corrected_sql is not None and request.question is not None)
        if planned_patches and (
            context.agent_memory.supports_tenant_keyed_tool_memory_upsert is not True
        ):
            raise FeedbackMemoryCapabilityError()

        record = FeedbackRecord(
            feedback_id=feedback_id,
            tenant_scope=tenant_scope,
            user_id=context.user.id,
            rating=request.rating,
            question=request.question,
            question_hash=_sha256(question_normalized) if question_normalized else None,
            original_sql=original_sql,
            original_sql_hash=_sha256(original_sql) if original_sql else None,
            corrected_sql=corrected_sql,
            corrected_sql_hash=_sha256(corrected_sql) if corrected_sql else None,
            correction_validated=corrected_sql is not None,
            reason_codes=request.reason_codes,
            user_edits=request.user_edits,
            conversation_id=context.conversation_id,
            request_id=context.request_id,
            created_at=now,
            planned_memory_patches=planned_patches,
            patched_memories=0,
            memory_patch_status="pending" if planned_patches else "applied",
            review_status="pending" if request.enqueue_for_review else None,
        )
        await self._store_call(self.store.create, record)

        if planned_patches:
            record = await self._apply_memory_patches(record, context)

        return FeedbackResult(
            feedback_id=feedback_id,
            patched_memories=record.patched_memories,
            memory_patch_status=record.memory_patch_status,
            review_queued=record.review_status == "pending",
        )

    async def retry_memory_patch(
        self,
        feedback_id: str,
        context: ToolContext,
    ) -> FeedbackResult:
        """Retry one durable patch outbox entry for its original principal."""

        tenant_scope = memory_scope_for_context(context)
        record = await self._store_call(self.store.get, tenant_scope, feedback_id)
        if (
            record is None
            or record.user_id != context.user.id
            or record.conversation_id != context.conversation_id
            or record.request_id != context.request_id
        ):
            raise PermissionError("feedback memory patch is outside principal scope")
        if record.memory_patch_status != "applied":
            record = await self._apply_memory_patches(record, context)
        return FeedbackResult(
            feedback_id=record.feedback_id,
            patched_memories=record.patched_memories,
            memory_patch_status=record.memory_patch_status,
            review_queued=record.review_status == "pending",
        )

    async def _apply_memory_patches(
        self,
        record: FeedbackRecord,
        context: ToolContext,
    ) -> FeedbackRecord:
        operations = self._memory_operations(
            record, record.review_status or "unreviewed"
        )
        if len(operations) != record.planned_memory_patches:
            raise FeedbackMemoryPatchError(record.feedback_id)

        patched = min(record.patched_memories, len(operations))
        try:
            for index, (patch_type, success, sql, metadata) in enumerate(operations):
                if index < patched:
                    continue
                await context.agent_memory.upsert_tenant_tool_usage(
                    question=record.question or "",
                    tool_name="run_sql",
                    args={"sql": sql},
                    context=context,
                    memory_key=f"{record.feedback_id}:{patch_type}",
                    success=success,
                    metadata=metadata,
                )
                patched += 1
        except Exception:
            try:
                await self._store_call(
                    self.store.record_memory_patch_attempt,
                    record.tenant_scope,
                    record.feedback_id,
                    status="failed",
                    patched_memories=patched,
                    error_code="memory_backend_error",
                )
            except Exception:
                pass
            raise FeedbackMemoryPatchError(record.feedback_id) from None

        return await self._store_call(
            self.store.record_memory_patch_attempt,
            record.tenant_scope,
            record.feedback_id,
            status="applied",
            patched_memories=patched,
            error_code=None,
        )

    @staticmethod
    def _memory_operations(
        record: FeedbackRecord,
        review_status: str,
    ) -> list[tuple[str, bool, str, dict[str, object]]]:
        question = record.question
        if question is None:
            raise FeedbackMemoryPatchError(record.feedback_id)
        active = review_status != "rejected"
        approved = review_status == "approved"
        provenance = {
            "feedback_id": record.feedback_id,
            "rating": record.rating,
            "reason_codes": record.reason_codes,
            "timestamp": record.created_at.isoformat(),
            "conversation_id": record.conversation_id,
            "request_id": record.request_id,
            "tenant_scope": record.tenant_scope,
            "feedback_user_id": record.user_id,
            "review_status": review_status,
            "active": active,
        }
        operations: list[tuple[str, bool, str, dict[str, object]]] = []
        if record.rating == "down" and record.original_sql and record.question:
            operations.append(
                (
                    "negative",
                    False,
                    record.original_sql,
                    {
                        "patch_type": "negative",
                        "weight": 4.0 if approved else (2.0 if active else 0.0),
                        "normalized_sql": record.original_sql.casefold(),
                        **provenance,
                    },
                )
            )
        if record.corrected_sql and record.question:
            operations.append(
                (
                    "corrective",
                    True,
                    record.corrected_sql,
                    {
                        "patch_type": "corrective",
                        "correction_validated": True,
                        "weight": 8.0 if approved else (5.0 if active else 0.0),
                        "normalized_sql": record.corrected_sql.casefold(),
                        **provenance,
                    },
                )
            )
        return operations

    async def _apply_review_memory_patch(
        self,
        record: FeedbackRecord,
        context: ToolContext,
    ) -> FeedbackRecord:
        if record.review_status not in {"approved", "rejected"}:
            raise FeedbackStateError("feedback review is not terminal")
        operations = self._memory_operations(record, record.review_status)
        try:
            for patch_type, success, sql, metadata in operations:
                await context.agent_memory.upsert_tenant_tool_usage(
                    question=record.question or "",
                    tool_name="run_sql",
                    args={"sql": sql},
                    context=context,
                    memory_key=f"{record.feedback_id}:{patch_type}",
                    success=success,
                    metadata=metadata,
                )
        except Exception:
            try:
                await self._store_call(
                    self.store.record_review_memory_patch_attempt,
                    record.tenant_scope,
                    record.feedback_id,
                    status="failed",
                    error_code="memory_backend_error",
                )
            except Exception:
                pass
            raise FeedbackReviewMemoryPatchError(record.feedback_id) from None

        return await self._store_call(
            self.store.record_review_memory_patch_attempt,
            record.tenant_scope,
            record.feedback_id,
            status="applied",
            error_code=None,
        )

    async def list_review_queue(
        self,
        context: ToolContext,
        *,
        status: ReviewStatus = "pending",
        limit: int = 100,
    ) -> FeedbackReviewQueue:
        self._require_admin(context)
        return FeedbackReviewQueue(
            records=await self._store_call(
                self.store.list_for_review,
                memory_scope_for_context(context),
                status=status,
                limit=limit,
            )
        )

    async def review_feedback(
        self,
        feedback_id: str,
        request: FeedbackReviewRequest,
        context: ToolContext,
    ) -> FeedbackReviewResult:
        self._require_admin(context)
        record = await self._store_call(
            self.store.transition_review,
            memory_scope_for_context(context),
            feedback_id,
            status=request.status,
            reviewer_id=context.user.id,
            reviewer_note=request.reviewer_note,
            reviewed_at=_utc_now().isoformat(),
        )
        if record.planned_memory_patches:
            record = await self._apply_review_memory_patch(record, context)
        return FeedbackReviewResult(record=record)

    async def retry_review_memory_patch(
        self,
        feedback_id: str,
        context: ToolContext,
    ) -> FeedbackReviewResult:
        """Retry a durable terminal review-memory outbox entry."""

        self._require_admin(context)
        record = await self._store_call(
            self.store.get,
            memory_scope_for_context(context),
            feedback_id,
        )
        if record is None or record.review_status not in {"approved", "rejected"}:
            raise PermissionError("reviewed feedback is outside tenant scope")
        if record.review_memory_patch_status != "applied":
            record = await self._apply_review_memory_patch(record, context)
        return FeedbackReviewResult(record=record)

    async def approved_export(self, context: ToolContext) -> TrainingExport:
        self._require_admin(context)
        tenant_scope = memory_scope_for_context(context)
        records = await self._store_call(
            self.store.list_approved,
            tenant_scope,
            limit=MAX_APPROVED_EXPORT_RECORDS + 1,
        )
        if len(records) > MAX_APPROVED_EXPORT_RECORDS:
            raise FeedbackExportLimitError("approved feedback record limit exceeded")
        lines: list[str] = []
        serialized_bytes = 0
        for record in records:
            line = json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n"
            serialized_bytes += len(line.encode("utf-8"))
            if serialized_bytes > MAX_APPROVED_EXPORT_BYTES:
                raise FeedbackExportLimitError("approved feedback byte limit exceeded")
            lines.append(line)
        content = "".join(lines)
        return TrainingExport(
            records=records,
            manifest=TrainingExportManifest(
                tenant_scope=tenant_scope,
                generated_at=_utc_now(),
                record_count=len(records),
                content_sha256=_sha256(content),
                feedback_ids=[record.feedback_id for record in records],
            ),
        )

    async def write_approved_export(
        self,
        context: ToolContext,
        output_path: str,
    ) -> TrainingExport:
        export = await self.approved_export(context)
        destination = Path(output_path)
        lines = [
            json.dumps(record.model_dump(mode="json"), sort_keys=True)
            for record in export.records
        ]
        content = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        if hashlib.sha256(content).hexdigest() != export.manifest.content_sha256:
            raise RuntimeError("approved feedback export serialization changed")
        manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
        manifest_content = (export.manifest.model_dump_json(indent=2) + "\n").encode(
            "utf-8"
        )

        await asyncio.to_thread(
            self._publish_export_generation,
            destination,
            manifest_path,
            content,
            manifest_content,
            export.manifest.content_sha256,
        )
        return export

    @staticmethod
    def _publish_export_generation(
        destination: Path,
        manifest_path: Path,
        content: bytes,
        manifest_content: bytes,
        content_sha256: str,
    ) -> None:
        parent_existed = destination.parent.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(destination.parent, 0o700)
        generation = _generation_path(destination, content_sha256)
        _atomic_write_private(generation, content)

        # The stable data path is a convenience copy. The manifest is the sole
        # commit marker, and readers resolve its digest to the immutable generation.
        # A crash before the final replace therefore leaves either manifest valid.
        _atomic_write_private(destination, content)
        _atomic_write_private(manifest_path, manifest_content)

    def _validate_correction(
        self,
        sql: Optional[str],
        context: ToolContext,
    ) -> Optional[str]:
        if sql is None:
            return None
        prepared = self.query_policy.prepare(sql, context)
        expression = sqlglot.parse_one(prepared, read=self.query_policy.dialect)
        return expression.sql(dialect=self.query_policy.dialect, pretty=False)

    def _normalize_untrusted_sql(self, sql: Optional[str]) -> Optional[str]:
        if sql is None:
            return None
        try:
            expressions = sqlglot.parse(sql, read=self.query_policy.dialect)
            if len(expressions) == 1 and expressions[0] is not None:
                return expressions[0].sql(
                    dialect=self.query_policy.dialect,
                    pretty=False,
                )
        except Exception:
            pass
        return " ".join(sql.split()).rstrip(";")

    @staticmethod
    def _validate_request_identity(
        request: FeedbackRequest,
        context: ToolContext,
    ) -> None:
        if request.conversation_id != context.conversation_id:
            raise PermissionError(
                "feedback conversation does not match request context"
            )
        if request.request_id != context.request_id:
            raise PermissionError("feedback request does not match request context")

    @staticmethod
    def _require_admin(context: ToolContext) -> None:
        if (
            not context.user.authenticated
            or "admin" not in context.user.group_memberships
        ):
            raise PermissionError("feedback review requires an authenticated admin")


class FeedbackMemoryPatchError(RuntimeError):
    """Stable retryable failure for a persisted feedback patch outbox entry."""

    def __init__(self, feedback_id: str) -> None:
        self.feedback_id = feedback_id
        super().__init__("Feedback was persisted but its memory patch failed.")


class FeedbackMemoryCapabilityError(RuntimeError):
    """Raised before persistence when retry-safe patch upsert is unavailable."""

    def __init__(self) -> None:
        super().__init__(
            "Feedback memory requires tenant-scoped keyed tool-memory upsert."
        )


class FeedbackReviewMemoryPatchError(RuntimeError):
    """Stable retryable failure for a persisted terminal review decision."""

    def __init__(self, feedback_id: str) -> None:
        self.feedback_id = feedback_id
        super().__init__(
            "Feedback review was persisted but its memory promotion failed."
        )


class FeedbackExportLimitError(RuntimeError):
    """Raised when an approved export exceeds its materialization budget."""


__all__ = [
    "FeedbackRecord",
    "FeedbackMemoryPatchError",
    "FeedbackMemoryCapabilityError",
    "FeedbackReviewMemoryPatchError",
    "FeedbackExportLimitError",
    "FeedbackRequest",
    "FeedbackResult",
    "FeedbackReviewQueue",
    "FeedbackReviewRequest",
    "FeedbackReviewResult",
    "FeedbackService",
    "TrainingExport",
]
