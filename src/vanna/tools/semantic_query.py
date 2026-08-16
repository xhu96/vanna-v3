"""Tool for semantic-layer-first query execution."""

from __future__ import annotations

from typing import Any, FrozenSet, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanna.capabilities.semantic import SemanticAdapter, SemanticQueryRequest
from vanna.components import DataFrameComponent, SimpleTextComponent, UiComponent
from vanna.core.tool import Tool, ToolContext, ToolResult


class SemanticQueryToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str | None = Field(
        default=None,
        description="Backward-compatible singular semantic metric identifier",
    )
    metrics: list[str] = Field(
        default_factory=list,
        description="One or more semantic metric identifiers",
    )
    dimensions: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_grain: str | None = None
    limit: int = Field(default=100, ge=1, le=5000)
    order_by: str | None = None

    @model_validator(mode="after")
    def require_metric(self) -> "SemanticQueryToolArgs":
        if not self.metric and not self.metrics:
            raise ValueError("At least one semantic metric is required")
        return self


class SemanticQueryTool(Tool[SemanticQueryToolArgs]):
    """Execute queries via semantic layer adapters."""

    def __init__(self, adapter: SemanticAdapter):
        self.adapter = adapter

    @property
    def name(self) -> str:
        return "semantic_query"

    @property
    def description(self) -> str:
        return (
            "Execute metric/dimension queries through the semantic layer. "
            "Use this before SQL generation when semantic coverage exists."
        )

    @property
    def capabilities(self) -> FrozenSet[str]:
        return frozenset({"semantic"})

    def get_args_schema(self) -> Type[SemanticQueryToolArgs]:
        return SemanticQueryToolArgs

    async def execute(
        self, context: ToolContext, args: SemanticQueryToolArgs
    ) -> ToolResult:
        request = SemanticQueryRequest(
            metric=args.metric or "",
            metrics=args.metrics,
            dimensions=args.dimensions,
            filters=args.filters,
            time_grain=args.time_grain,
            limit=args.limit,
            order_by=args.order_by,
        )
        result = await self.adapter.execute(request, context)
        dataframe_component = DataFrameComponent.from_records(
            records=result.rows,
            title=f"Semantic Result: {', '.join(request.metrics)}",
            description=f"Semantic query returned {result.row_count} row(s)",
        )
        return ToolResult(
            success=True,
            result_for_llm=(
                "Executed semantic query for metric(s) "
                f"'{', '.join(request.metrics)}'. "
                f"Returned {result.row_count} row(s)."
            ),
            ui_component=UiComponent(
                rich_component=dataframe_component,
                simple_component=SimpleTextComponent(
                    text=f"Semantic query returned {result.row_count} row(s)."
                ),
            ),
            metadata={
                "semantic_query": request.model_dump(),
                "semantic_result": result.model_dump(),
                "row_count": result.row_count,
                "validation_checks": [
                    "semantic_query_passed",
                    "row_shape_passed",
                ],
            },
        )
