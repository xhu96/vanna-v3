"""Tool for semantic-layer-first query execution."""

from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel, Field

from vanna.capabilities.semantic import SemanticAdapter, SemanticQueryRequest
from vanna.components import DataFrameComponent, SimpleTextComponent, UiComponent
from vanna.core.tool import Tool, ToolContext, ToolResult


class SemanticQueryToolArgs(BaseModel):
    metric: str = Field(description="Semantic metric identifier")
    dimensions: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_grain: str | None = None
    limit: int = 100
    order_by: str | None = None


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

    def get_args_schema(self) -> Type[SemanticQueryToolArgs]:
        return SemanticQueryToolArgs

    async def execute(
        self, context: ToolContext, args: SemanticQueryToolArgs
    ) -> ToolResult:
        request = SemanticQueryRequest(
            metric=args.metric,
            dimensions=args.dimensions,
            filters=args.filters,
            time_grain=args.time_grain,
            limit=args.limit,
            order_by=args.order_by,
        )
        result = await self.adapter.execute(request, context)
        dataframe_component = DataFrameComponent.from_records(
            records=result.rows,
            title=f"Semantic Result: {args.metric}",
            description=f"Semantic query returned {result.row_count} row(s)",
        )
        return ToolResult(
            success=True,
            result_for_llm=(
                f"Executed semantic query for metric '{args.metric}'. "
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
            },
        )
