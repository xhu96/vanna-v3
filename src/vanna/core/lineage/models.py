"""Lineage and evidence models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ColumnLineageEdge:
    """A single source-to-output column mapping extracted from a SQL statement.

    Attributes:
        source_table: The table qualifier as written in the query (``"unknown"``
            when the column has no explicit qualifier, ``"*"`` for wildcards).
        column: The column name, or ``"*"`` for wildcard selections.
        alias: The output alias declared in the SELECT list, if any.
    """

    source_table: str
    column: str
    alias: Optional[str] = None


@dataclass
class ToolLineageRecord:
    tool_name: str
    success: bool
    execution_time_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class MemoryEvidence:
    memory_id: Optional[str]
    score: Optional[float]
    tool_name: Optional[str] = None


@dataclass
class SqlEvidence:
    sql: str
    row_count: Optional[int] = None
    execution_time_ms: Optional[float] = None


@dataclass
class LineageEvidence:
    schema_hash: Optional[str] = None
    schema_snapshot_id: Optional[str] = None
    tool_calls: List[ToolLineageRecord] = field(default_factory=list)
    retrieved_memories: List[MemoryEvidence] = field(default_factory=list)
    sql_executions: List[SqlEvidence] = field(default_factory=list)
    validation_checks: List[str] = field(default_factory=list)
    column_lineage: List[ColumnLineageEdge] = field(default_factory=list)
    confidence: str = "Low"
