"""Validation for byte-bound, approved-only feedback training exports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from vanna.services.feedback_models import FeedbackRecord

FEEDBACK_MANIFEST_VERSION = "vanna-feedback-export-v1"
MAX_EXPORT_BYTES = 256 * 1024 * 1024
MAX_EXPORT_RECORDS = 100_000


class TrainingDataValidationError(ValueError):
    """Raised when approved training provenance cannot be verified."""


def validate_training_manifest(value: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "tenant_scope",
        "generated_at",
        "record_count",
        "content_sha256",
        "feedback_ids",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise TrainingDataValidationError(
            "approved feedback manifest has invalid shape"
        )
    if value.get("schema_version") != FEEDBACK_MANIFEST_VERSION:
        raise TrainingDataValidationError(
            "approved feedback manifest version is unsupported"
        )

    tenant_scope = value.get("tenant_scope")
    generated_at = value.get("generated_at")
    record_count = value.get("record_count")
    digest = value.get("content_sha256")
    feedback_ids = value.get("feedback_ids")
    if not isinstance(tenant_scope, str) or not tenant_scope.startswith("tenant:"):
        raise TrainingDataValidationError("approved feedback tenant_scope is invalid")
    if not isinstance(generated_at, str):
        raise TrainingDataValidationError("approved feedback generated_at is invalid")
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise TrainingDataValidationError(
            "approved feedback generated_at is invalid"
        ) from error
    if timestamp.tzinfo is None:
        raise TrainingDataValidationError(
            "approved feedback generated_at must include a timezone"
        )
    if (
        isinstance(record_count, bool)
        or not isinstance(record_count, int)
        or not 0 <= record_count <= MAX_EXPORT_RECORDS
    ):
        raise TrainingDataValidationError("approved feedback record_count is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise TrainingDataValidationError("approved feedback content_sha256 is invalid")
    if (
        not isinstance(feedback_ids, list)
        or len(feedback_ids) != record_count
        or len(feedback_ids) != len(set(feedback_ids))
        or any(
            not isinstance(feedback_id, str)
            or not feedback_id
            or len(feedback_id) > 160
            for feedback_id in feedback_ids
        )
    ):
        raise TrainingDataValidationError(
            "approved feedback IDs do not match record_count"
        )
    return {
        "schema_version": FEEDBACK_MANIFEST_VERSION,
        "tenant_scope": tenant_scope,
        "generated_at": generated_at,
        "record_count": record_count,
        "content_sha256": digest,
        "feedback_ids": list(feedback_ids),
    }


def validate_training_export_bytes(
    manifest: Any,
    content: bytes,
) -> dict[str, Any]:
    """Bind a manifest to exact approved JSONL bytes and typed records."""

    normalized = validate_training_manifest(manifest)
    if len(content) > MAX_EXPORT_BYTES:
        raise TrainingDataValidationError("approved feedback export exceeds size limit")
    if hashlib.sha256(content).hexdigest() != normalized["content_sha256"]:
        raise TrainingDataValidationError(
            "approved feedback export digest does not match"
        )
    if content and not content.endswith(b"\n"):
        raise TrainingDataValidationError(
            "approved feedback JSONL must end with a newline"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TrainingDataValidationError(
            "approved feedback JSONL must be UTF-8"
        ) from error

    lines = text.splitlines()
    if len(lines) != normalized["record_count"]:
        raise TrainingDataValidationError(
            "approved feedback JSONL count does not match manifest"
        )

    records: list[FeedbackRecord] = []
    for index, line in enumerate(lines, start=1):
        if not line:
            raise TrainingDataValidationError(
                f"approved feedback JSONL line {index} is empty"
            )
        try:
            value = json.loads(line)
            record = FeedbackRecord.model_validate(value)
        except (json.JSONDecodeError, ValueError) as error:
            raise TrainingDataValidationError(
                f"approved feedback JSONL line {index} is invalid"
            ) from error
        if record.review_status != "approved":
            raise TrainingDataValidationError(
                "training export contains unapproved feedback"
            )
        if record.tenant_scope != normalized["tenant_scope"]:
            raise TrainingDataValidationError("training export crosses tenant scope")
        if record.reviewer_id is None or record.reviewed_at is None:
            raise TrainingDataValidationError(
                "approved feedback lacks review provenance"
            )
        if record.corrected_sql is not None and not record.correction_validated:
            raise TrainingDataValidationError(
                "training export has unvalidated corrected SQL"
            )
        if record.memory_patch_status != "applied":
            raise TrainingDataValidationError(
                "training export has an unresolved memory patch"
            )
        if (
            record.planned_memory_patches
            and record.review_memory_patch_status != "applied"
        ):
            raise TrainingDataValidationError(
                "training export has an unresolved review-memory patch"
            )
        records.append(record)

    record_ids = [record.feedback_id for record in records]
    if record_ids != normalized["feedback_ids"]:
        raise TrainingDataValidationError(
            "approved feedback JSONL IDs do not match manifest order"
        )
    return normalized


def load_training_export(manifest_path: Path, records_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingDataValidationError(
            "cannot load approved feedback export"
        ) from error
    normalized = validate_training_manifest(manifest)
    generation_path = (
        records_path.parent
        / f".{records_path.name}.generations"
        / f"{normalized['content_sha256']}.jsonl"
    )
    try:
        # V3 writers publish immutable digest-addressed generations and atomically
        # replace only the manifest commit marker. Legacy exports still load from
        # the caller-supplied JSONL path.
        content = (
            generation_path.read_bytes()
            if generation_path.is_file()
            else records_path.read_bytes()
        )
    except OSError as error:
        raise TrainingDataValidationError(
            "cannot load approved feedback export"
        ) from error
    return validate_training_export_bytes(manifest, content)


__all__ = [
    "FEEDBACK_MANIFEST_VERSION",
    "MAX_EXPORT_BYTES",
    "MAX_EXPORT_RECORDS",
    "TrainingDataValidationError",
    "load_training_export",
    "validate_training_export_bytes",
    "validate_training_manifest",
]
