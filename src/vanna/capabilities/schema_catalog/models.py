"""Typed schema catalog, drift, and memory-patch models."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import List, Literal, Optional, Sequence
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def normalize_scope_id(value: str, label: str = "tenant_id") -> str:
    """Validate a bounded identifier before it is used as a storage scope."""

    normalized = value.strip()
    if not _SAFE_ID.fullmatch(normalized) or ".." in normalized:
        raise ValueError(f"{label} must be a bounded storage identifier")
    return normalized


def encode_schema_entity_component(value: str) -> str:
    """Escape one catalog component so dots remain structural separators."""

    return quote(value, safe="_-~").replace(".", "%2E")


class SchemaColumn(BaseModel):
    """Canonical portable column descriptor."""

    model_config = ConfigDict(extra="forbid")

    schema_name: Optional[str] = Field(default=None, max_length=256)
    table_name: str = Field(min_length=1, max_length=256)
    column_name: str = Field(min_length=1, max_length=256)
    data_type: str = Field(min_length=1, max_length=512)
    is_nullable: Optional[bool] = None
    ordinal_position: Optional[int] = Field(default=None, ge=1)

    @field_validator("schema_name", "table_name", "column_name", "data_type")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("schema descriptors cannot be empty or contain controls")
        return normalized

    @property
    def entity_id(self) -> str:
        """Return a stable fully qualified column identifier."""

        return ".".join(
            encode_schema_entity_component(part)
            for part in (self.schema_name, self.table_name, self.column_name)
            if part
        )


def canonical_schema_hash(columns: Sequence[SchemaColumn]) -> str:
    """Hash canonical column descriptors independent of input ordering."""

    normalized = sorted(
        (
            {
                "schema_name": column.schema_name or "",
                "table_name": column.table_name,
                "column_name": column.column_name,
                "data_type": column.data_type.casefold(),
                "is_nullable": column.is_nullable,
                "ordinal_position": column.ordinal_position,
            }
            for column in columns
        ),
        key=lambda column: (
            column["schema_name"],
            column["table_name"],
            column["ordinal_position"] or 2**31,
            column["column_name"],
        ),
    )
    content = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SchemaSnapshot(BaseModel):
    """Immutable tenant-scoped catalog snapshot."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    schema_version: int = Field(ge=1)
    captured_at: datetime = Field(default_factory=utc_now)
    dialect: str = Field(default="unknown", min_length=1, max_length=64)
    schema_hash: str
    previous_snapshot_id: Optional[str] = Field(default=None, max_length=256)
    columns: List[SchemaColumn] = Field(default_factory=list, max_length=500_000)

    @field_validator("snapshot_id", "tenant_id")
    @classmethod
    def validate_storage_ids(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "identifier")
        return normalize_scope_id(value, str(field_name))

    @field_validator("schema_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("schema_hash must be a lowercase SHA-256 digest")
        return value

    @field_validator("dialect")
    @classmethod
    def normalize_dialect(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,64}", normalized):
            raise ValueError("dialect must be a bounded identifier")
        return normalized

    @field_validator("captured_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def canonicalize_columns(self) -> "SchemaSnapshot":
        ordered = sorted(
            self.columns,
            key=lambda column: (
                column.schema_name or "",
                column.table_name,
                column.ordinal_position or 2**31,
                column.column_name,
            ),
        )
        keys = [
            (column.schema_name or "", column.table_name, column.column_name)
            for column in ordered
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("schema snapshot contains duplicate columns")
        self.columns = ordered
        if canonical_schema_hash(ordered) != self.schema_hash:
            raise ValueError("schema snapshot hash does not match its columns")
        return self


class SchemaDiff(BaseModel):
    """Column-level drift with reproducible snapshot provenance."""

    model_config = ConfigDict(extra="forbid")

    previous_schema_hash: Optional[str] = None
    current_schema_hash: str
    previous_schema_version: Optional[int] = Field(default=None, ge=1)
    current_schema_version: int = Field(ge=1)
    previous_snapshot_id: Optional[str] = None
    current_snapshot_id: str
    added_columns: List[SchemaColumn] = Field(default_factory=list)
    removed_columns: List[SchemaColumn] = Field(default_factory=list)
    changed_columns: List[SchemaColumn] = Field(default_factory=list)
    added_entities: List[str] = Field(default_factory=list)
    removed_entities: List[str] = Field(default_factory=list)
    changed_entities: List[str] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.added_columns or self.removed_columns or self.changed_columns)


SchemaPatchAction = Literal["summary", "upsert", "tombstone"]


class SchemaMemoryPatch(BaseModel):
    """Durable outbox record for immediate schema-memory synchronization."""

    model_config = ConfigDict(extra="forbid")

    patch_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    snapshot_id: str = Field(min_length=1, max_length=256)
    schema_version: int = Field(ge=1)
    schema_hash: str
    action: SchemaPatchAction
    entity_id: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1, max_length=64 * 1024)
    provenance: str = "schema_catalog_drift"
    weight: float = Field(default=2.0, gt=0, le=10)

    @field_validator("tenant_id", "snapshot_id", "patch_id")
    @classmethod
    def validate_ids(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "identifier")
        return normalize_scope_id(value, str(field_name))

    @field_validator("schema_hash")
    @classmethod
    def validate_patch_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("schema_hash must be a lowercase SHA-256 digest")
        return value


class SchemaSyncResult(BaseModel):
    """Observable result of one idempotent synchronization attempt."""

    model_config = ConfigDict(extra="forbid")

    snapshot: SchemaSnapshot
    diff: SchemaDiff
    persisted: bool
    memory_patches_applied: List[str] = Field(default_factory=list)
    memory_patches_pending: int = Field(default=0, ge=0)
