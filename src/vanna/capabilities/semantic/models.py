"""Semantic-layer query models."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SemanticCoverage = Literal["full", "partial", "missing"]


class SemanticQueryRequest(BaseModel):
    metric: str
    dimensions: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    time_grain: Optional[str] = None
    limit: Optional[int] = 100
    order_by: Optional[str] = None


class SemanticPlanHint(BaseModel):
    coverage: SemanticCoverage
    reason: str
    request: Optional[SemanticQueryRequest] = None


class SemanticQueryResult(BaseModel):
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

