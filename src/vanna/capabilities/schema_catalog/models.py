"""Schema catalog models for drift detection."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SchemaColumn(BaseModel):
    schema_name: Optional[str] = None
    table_name: str
    column_name: str
    data_type: str
    is_nullable: Optional[bool] = None


class SchemaSnapshot(BaseModel):
    snapshot_id: str
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    dialect: str = "unknown"
    schema_hash: str
    columns: List[SchemaColumn] = Field(default_factory=list)


class SchemaDiff(BaseModel):
    previous_schema_hash: Optional[str] = None
    current_schema_hash: str
    added_columns: List[SchemaColumn] = Field(default_factory=list)
    removed_columns: List[SchemaColumn] = Field(default_factory=list)
    changed_columns: List[SchemaColumn] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.added_columns or self.removed_columns or self.changed_columns)


class SchemaSyncResult(BaseModel):
    snapshot: SchemaSnapshot
    diff: SchemaDiff
