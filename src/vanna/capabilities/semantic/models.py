"""Semantic-layer query models."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


SemanticCoverage = Literal["full", "partial", "missing"]
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")


def _normalize_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{label} must be a bounded semantic identifier")
    return normalized


class SemanticQueryRequest(BaseModel):
    """Typed semantic query with a V2-compatible singular metric alias."""

    model_config = ConfigDict(extra="forbid")

    metric: str = ""
    metrics: List[str] = Field(default_factory=list, max_length=20)
    dimensions: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    time_grain: Optional[str] = None
    limit: Optional[int] = Field(default=100, ge=1, le=5000)
    order_by: Optional[str] = None

    @model_validator(mode="after")
    def normalize_request(self) -> "SemanticQueryRequest":
        raw_metrics = ([self.metric] if self.metric.strip() else []) + self.metrics
        metrics: List[str] = []
        for raw_metric in raw_metrics:
            metric = _normalize_identifier(raw_metric, "metric")
            if metric not in metrics:
                metrics.append(metric)
        if not metrics:
            raise ValueError("At least one semantic metric is required")

        dimensions: List[str] = []
        for raw_dimension in self.dimensions:
            dimension = _normalize_identifier(raw_dimension, "dimension")
            if dimension not in dimensions:
                dimensions.append(dimension)
        if len(dimensions) > 100:
            raise ValueError("Semantic queries allow at most 100 dimensions")
        if len(self.filters) > 100:
            raise ValueError("Semantic queries allow at most 100 filters")

        self.metric = metrics[0]
        self.metrics = metrics
        self.dimensions = dimensions
        self.filters = {
            _normalize_identifier(name, "filter dimension"): value
            for name, value in self.filters.items()
        }
        if self.time_grain is not None:
            self.time_grain = self.time_grain.strip().lower()
            if not self.time_grain:
                raise ValueError("time_grain cannot be empty")
        if self.order_by is not None:
            self.order_by = self.order_by.strip()
            if not self.order_by:
                raise ValueError("order_by cannot be empty")
        return self


class SemanticPlanHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage: SemanticCoverage
    reason: str
    request: Optional[SemanticQueryRequest] = None


class SemanticQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
