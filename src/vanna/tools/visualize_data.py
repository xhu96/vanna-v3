"""Tool for visualizing DataFrame data from CSV files."""

import io
import logging
from typing import Any, Literal, Optional, Type, cast

import pandas as pd
from pydantic import BaseModel, Field

from vanna.components import (
    ChartComponent,
    ComponentType,
    NotificationComponent,
    SimpleTextComponent,
    UiComponent,
)
from vanna.core.chart_spec import (
    MAX_CHART_FIELDS,
    MAX_CHART_ROWS,
    ChartSpec,
    dataframe_to_vega_lite_spec,
    normalize_plotly_json_spec,
)
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.core.tool.errors import public_tool_failure
from vanna.integrations.plotly import PlotlyChartGenerator

from .file_system import FileSystem, LocalFileSystem

logger = logging.getLogger(__name__)


class VisualizeDataArgs(BaseModel):
    """Arguments for visualize_data tool."""

    filename: str = Field(description="Name of the CSV file to visualize")
    title: Optional[str] = Field(
        default=None, description="Optional title for the chart"
    )
    format: Literal["vega-lite", "plotly-json"] = Field(
        default="vega-lite",
        description="Declarative chart format: 'vega-lite' (default) or 'plotly-json'",
    )


class VisualizeDataTool(Tool[VisualizeDataArgs]):
    """Read CSV data and return a validated declarative chart."""

    def __init__(
        self,
        file_system: Optional[FileSystem] = None,
        plotly_generator: Optional[PlotlyChartGenerator] = None,
    ):
        """Initialize the tool with injected file and chart services.

        Args:
            file_system: CSV storage, defaulting to a local file system.
            plotly_generator: Trusted heuristic generator whose output is reduced to
                the safe Plotly JSON profile.
        """
        self.file_system = file_system or LocalFileSystem()
        self.plotly_generator = plotly_generator or PlotlyChartGenerator()

    @property
    def name(self) -> str:
        return "visualize_data"

    @property
    def description(self) -> str:
        return (
            "Create a validated declarative visualization from a CSV file "
            "without executing generated code."
        )

    def get_args_schema(self) -> Type[VisualizeDataArgs]:
        return VisualizeDataArgs

    async def execute(
        self, context: ToolContext, args: VisualizeDataArgs
    ) -> ToolResult:
        """Read CSV file and generate visualization."""
        try:
            logger.info("Starting visualization for file: %s", args.filename)

            # Read the CSV file using FileSystem
            csv_content = await self.file_system.read_file(args.filename, context)
            logger.info("Read %d bytes from CSV file", len(csv_content))

            # Parse CSV into DataFrame
            df = pd.read_csv(io.StringIO(csv_content))
            logger.info(
                "Parsed DataFrame with shape %s and %d columns",
                df.shape,
                len(df.columns),
            )

            if len(df.columns) > MAX_CHART_FIELDS:
                raise ValueError(
                    f"Dataset has {len(df.columns)} columns; "
                    f"safe charts allow at most {MAX_CHART_FIELDS}."
                )

            # Generate title
            title = args.title or f"Visualization of {args.filename}"

            # Build declarative chart spec (safe-by-default).
            row_count = len(df)
            chart_df = df.head(MAX_CHART_ROWS)
            records = cast("list[dict[str, Any]]", chart_df.to_dict(orient="records"))
            columns = df.columns.tolist()
            column_types = self._infer_column_types(df)
            if args.format == "plotly-json":
                generated_chart = self.plotly_generator.generate_chart(chart_df, title)
                chart_dict = normalize_plotly_json_spec(generated_chart)
                metadata: dict[str, Any] = {
                    "row_count": row_count,
                    "columns": columns,
                }
                if row_count > len(records):
                    metadata["truncated"] = True
                chart_spec = ChartSpec(
                    format="plotly-json",
                    schema_version="plotly-safe-1",
                    spec=chart_dict,
                    dataset=records,
                    metadata=metadata,
                )
            else:
                chart_spec = dataframe_to_vega_lite_spec(
                    rows=records,
                    columns=columns,
                    column_types=column_types,
                    title=title,
                    row_count=row_count,
                )

            chart_payload = chart_spec.model_dump()

            # Create result message
            col_count = len(df.columns)
            result = (
                f"Created declarative chart spec from '{args.filename}' "
                f"({row_count} rows, {col_count} columns)."
            )

            # Create ChartComponent
            logger.info("Creating ChartComponent...")
            chart_component = ChartComponent(
                chart_type="declarative",
                data=chart_payload,
                title=title,
                config={
                    "data_shape": {"rows": row_count, "columns": col_count},
                    "source_file": args.filename,
                    "chart_format": chart_spec.format,
                },
            )
            logger.info("ChartComponent created successfully")

            logger.info("Creating ToolResult...")
            tool_result = ToolResult(
                success=True,
                result_for_llm=result,
                ui_component=UiComponent(
                    rich_component=chart_component,
                    simple_component=SimpleTextComponent(text=result),
                ),
                metadata={
                    "filename": args.filename,
                    "rows": row_count,
                    "columns": col_count,
                    "chart_spec": chart_payload,
                },
            )
            logger.info("ToolResult created successfully")
            return tool_result

        except FileNotFoundError:
            logger.warning(
                "Visualization input was not found request_id=%s", context.request_id
            )
            error_message = f"File not found: {args.filename}"
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=error_message,
                metadata={"error_type": "file_not_found"},
            )
        except pd.errors.ParserError:
            logger.warning(
                "Visualization CSV parse failed request_id=%s", context.request_id
            )
            error_message = f"Failed to parse CSV file '{args.filename}'."
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=error_message,
                metadata={"error_type": "csv_parse_error"},
            )
        except ValueError as error:
            error_message, failure_metadata = public_tool_failure(
                operation="Visualization safety validation",
                code="visualization_error",
                error=error,
            )
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=error_message,
                metadata=failure_metadata,
            )
        except Exception as error:
            error_message, failure_metadata = public_tool_failure(
                operation="Visualization",
                code="general_error",
                error=error,
            )
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=error_message,
                metadata=failure_metadata,
            )

    def _infer_column_types(self, df: pd.DataFrame) -> dict[str, str]:
        """Map dataframe dtypes into Vega-Lite encoding types."""
        types = {}
        for column in df.columns:
            dtype = df[column].dtype
            if pd.api.types.is_datetime64_any_dtype(dtype):
                types[column] = "temporal"
            elif pd.api.types.is_numeric_dtype(dtype):
                types[column] = "quantitative"
            else:
                types[column] = "nominal"
        return types
