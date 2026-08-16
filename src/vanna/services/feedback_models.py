"""Typed feedback, review, and approved-export records."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReviewStatus = Literal["pending", "approved", "rejected"]
MemoryPatchStatus = Literal["pending", "applied", "failed"]
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        revalidate_instances="always",
    )


class FeedbackRequest(_StrictModel):
    rating: Literal["up", "down"]
    question: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    original_sql: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    corrected_sql: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    reason_codes: List[str] = Field(default_factory=list, max_length=20)
    user_edits: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    conversation_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    enqueue_for_review: bool = False

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: List[str]) -> List[str]:
        if len(values) != len(set(values)) or any(
            not _REASON_CODE.fullmatch(value) for value in values
        ):
            raise ValueError("reason codes must be unique stable identifiers")
        return values

    @field_validator("conversation_id", "request_id")
    @classmethod
    def validate_reference_ids(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("feedback reference IDs cannot contain control characters")
        return value

    @model_validator(mode="after")
    def validate_patch_inputs(self) -> "FeedbackRequest":
        if self.corrected_sql is not None and self.question is None:
            raise ValueError("corrected SQL requires the original question")
        if (
            self.rating == "down"
            and self.original_sql is not None
            and self.question is None
        ):
            raise ValueError("negative SQL feedback requires the original question")
        return self


class FeedbackReviewRequest(_StrictModel):
    status: Literal["approved", "rejected"]
    reviewer_note: Optional[str] = Field(default=None, max_length=10_000)


class FeedbackRecord(_StrictModel):
    feedback_id: str = Field(min_length=1, max_length=160)
    tenant_scope: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=256)
    rating: Literal["up", "down"]
    question: Optional[str] = Field(default=None, max_length=100_000)
    question_hash: Optional[str] = Field(default=None, max_length=64)
    original_sql: Optional[str] = Field(default=None, max_length=100_000)
    original_sql_hash: Optional[str] = Field(default=None, max_length=64)
    corrected_sql: Optional[str] = Field(default=None, max_length=100_000)
    corrected_sql_hash: Optional[str] = Field(default=None, max_length=64)
    correction_validated: bool = False
    reason_codes: List[str] = Field(default_factory=list, max_length=20)
    user_edits: Optional[str] = Field(default=None, max_length=100_000)
    conversation_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    created_at: datetime
    planned_memory_patches: int = Field(default=0, ge=0, le=2)
    patched_memories: int = Field(default=0, ge=0, le=2)
    memory_patch_status: MemoryPatchStatus = "applied"
    memory_patch_attempts: int = Field(default=0, ge=0)
    memory_patch_error_code: Optional[str] = Field(default=None, max_length=64)
    review_status: Optional[ReviewStatus] = None
    reviewer_id: Optional[str] = Field(default=None, max_length=256)
    reviewer_note: Optional[str] = Field(default=None, max_length=10_000)
    reviewed_at: Optional[datetime] = None
    review_memory_patch_status: Optional[MemoryPatchStatus] = None
    review_memory_patch_attempts: int = Field(default=0, ge=0)
    review_memory_patch_error_code: Optional[str] = Field(default=None, max_length=64)


class FeedbackResult(_StrictModel):
    feedback_id: str
    patched_memories: int = Field(ge=0, le=2)
    memory_patch_status: MemoryPatchStatus
    review_queued: bool
    status: Literal["accepted"] = "accepted"


class FeedbackReviewResult(_StrictModel):
    record: FeedbackRecord


class FeedbackReviewQueue(_StrictModel):
    records: List[FeedbackRecord]


class TrainingExportManifest(_StrictModel):
    schema_version: Literal["vanna-feedback-export-v1"] = "vanna-feedback-export-v1"
    tenant_scope: str
    generated_at: datetime
    record_count: int = Field(ge=0)
    content_sha256: str = Field(min_length=64, max_length=64)
    feedback_ids: List[str]


class TrainingExport(_StrictModel):
    records: List[FeedbackRecord]
    manifest: TrainingExportManifest


__all__ = [
    "FeedbackRecord",
    "FeedbackRequest",
    "FeedbackResult",
    "FeedbackReviewQueue",
    "FeedbackReviewRequest",
    "FeedbackReviewResult",
    "MemoryPatchStatus",
    "ReviewStatus",
    "TrainingExport",
    "TrainingExportManifest",
]
