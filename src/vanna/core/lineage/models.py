"""Typed internal models for reproducible answer evidence."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConfidenceTier = Literal["High", "Medium", "Low"]
LineageOutcome = Literal["completed", "workflow", "tool_limit", "error"]
SemanticCoverage = Literal["full", "partial", "missing", "not_applicable"]


class _LineageModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        revalidate_instances="always",
    )


class ToolLineageRecord(_LineageModel):
    tool_name: str = Field(min_length=1, max_length=160)
    success: bool
    execution_time_ms: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)


class RetrievedSourceEvidence(_LineageModel):
    source_id: str = Field(min_length=1, max_length=160)
    kind: Literal["memory", "document"] = "memory"
    score: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @property
    def memory_id(self) -> str:
        """Retain the original collector attribute for compatibility."""

        return self.source_id


class SqlEvidence(_LineageModel):
    sql: str = Field(min_length=1, max_length=100_000)
    dialect: Optional[str] = Field(default=None, max_length=64)
    row_count: int = Field(default=0, ge=0)
    execution_time_ms: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)


class ValidationCheck(_LineageModel):
    name: str = Field(min_length=1, max_length=160)
    passed: bool


class SemanticEvidence(_LineageModel):
    coverage: SemanticCoverage = "not_applicable"
    metric_names: List[str] = Field(default_factory=list, max_length=100)
    fallback_reason: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("metric_names")
    @classmethod
    def unique_metric_names(cls, values: List[str]) -> List[str]:
        if len(values) != len(set(values)) or any(
            not value or len(value) > 256 for value in values
        ):
            raise ValueError("semantic metric names must be unique bounded strings")
        return values


class ConfidenceEvidence(_LineageModel):
    tier: ConfidenceTier = "Low"
    signals: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("signals")
    @classmethod
    def unique_signals(cls, values: List[str]) -> List[str]:
        if len(values) != len(set(values)) or any(
            not value or len(value) > 160 for value in values
        ):
            raise ValueError("confidence signals must be unique bounded strings")
        return values


class LineageEvidence(_LineageModel):
    """Request-wide evidence retained internally before permission filtering."""

    request_id: Optional[str] = Field(default=None, max_length=160)
    conversation_id: Optional[str] = Field(default=None, max_length=160)
    outcome: LineageOutcome = "completed"
    failure_code: Optional[str] = Field(default=None, max_length=160)
    schema_version: Optional[int] = Field(default=None, ge=1)
    schema_hash: Optional[str] = Field(default=None, max_length=160)
    schema_snapshot_id: Optional[str] = Field(default=None, max_length=160)
    schema_drifted: bool = False
    semantic: SemanticEvidence = Field(default_factory=SemanticEvidence)
    tool_calls: List[ToolLineageRecord] = Field(default_factory=list, max_length=1000)
    retrieved_memories: List[RetrievedSourceEvidence] = Field(
        default_factory=list,
        max_length=1000,
    )
    sql_executions: List[SqlEvidence] = Field(default_factory=list, max_length=100)
    validation_checks: List[ValidationCheck] = Field(
        default_factory=list,
        max_length=1000,
    )
    redactions: List[str] = Field(default_factory=list, max_length=20)
    confidence: ConfidenceEvidence = Field(default_factory=ConfidenceEvidence)


# The former name was exposed by this module while lineage was experimental.
MemoryEvidence = RetrievedSourceEvidence
