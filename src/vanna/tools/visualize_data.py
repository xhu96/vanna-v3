"""Tool for visualizing DataFrame data from CSV files."""

from typing import Optional, Type
import logging
import pandas as pd
from pydantic import BaseModel, Field

from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.core.chart_spec import ChartSpec, dataframe_to_vega_lite_spec
from vanna.components import (
    UiComponent,
    ChartComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)

from .file_system import FileSystem, LocalFileSystem
from vanna.integrations.plotly import PlotlyChartGenerator

logger = logging.getLogger(__name__)


class VisualizeDataArgs(BaseModel):
    """Arguments for visualize_data tool."""

    filename: str = Field(description="Name of the CSV file to visualize")
    title: Optional[str] = Field(
        default=None, description="Optional title for the chart"
    )
    format: str = Field(
        default="vega-lite",
        description="Declarative chart format: 'vega-lite' (default) or 'plotly-json'",
    )


class VisualizeDataTool(Tool[VisualizeDataArgs]):
    """Tool that reads CSV files and generates visualizations using dependency injection."""

    def __init__(
        self,
        file_system: Optional[FileSystem] = None,
        plotly_generator: Optional[PlotlyChartGenerator] = None,
    ):
        """Initialize the tool with FileSystem and PlotlyChartGenerator.

        Args:
            file_system: FileSystem implementation for reading CSV files (defaults to LocalFileSystem)
            plotly_generator: PlotlyChartGenerator for creating Plotly charts (defaults to PlotlyChartGenerator())
        """
        self.file_system = file_system or LocalFileSystem()
        self.plotly_generator = plotly_generator or PlotlyChartGenerator()

    @property
    def name(self) -> str:
        return "visualize_data"

    @property
    def description(self) -> str:
        return "Create a visualization from a CSV file. The tool automatically selects an appropriate chart type based on the data."

    def get_args_schema(self) -> Type[VisualizeDataArgs]:
        return VisualizeDataArgs

    async def execute(
        self, context: ToolContext, args: VisualizeDataArgs
    ) -> ToolResult:
        """Read CSV file and generate visualization."""
        try:
            logger.info(f"Starting visualization for file: {args.filename}")

            # Read the CSV file using FileSystem
            csv_content = await self.file_system.read_file(args.filename, context)
            logger.info(f"Read {len(csv_content)} bytes from CSV file")

            # Parse CSV into DataFrame
            import io

            df = pd.read_csv(io.StringIO(csv_content))
            logger.info(
                f"Parsed DataFrame with shape {df.shape}, columns: {df.columns.tolist()}, dtypes: {df.dtypes.to_dict()}"
            )

            # Generate title
            title = args.title or f"Visualization of {args.filename}"

            # Build declarative chart spec (safe-by-default).
            records = df.head(500).to_dict("records")
            column_types = self._infer_column_types(df)
            if args.format == "plotly-json":
                chart_dict = self.plotly_generator.generate_chart(df, title)
                chart_spec = ChartSpec(
                    format="plotly-json",
                    schema_version="v1",
                    spec=chart_dict,
                    dataset=records,
                    metadata={"source_file": args.filename},
                )
            else:
                chart_spec = dataframe_to_vega_lite_spec(
                    rows=records,
                    columns=df.columns.tolist(),
                    column_types=column_types,
                    title=title,
                )
                chart_spec.metadata["source_file"] = args.filename

            # Create result message
            row_count = len(df)
            col_count = len(df.columns)
            result = (
                f"Created declarative chart spec from '{args.filename}' "
                f"({row_count} rows, {col_count} columns)."
            )

            # Create ChartComponent
            logger.info("Creating ChartComponent...")
            chart_component = ChartComponent(
                chart_type="declarative",
                data=chart_spec.model_dump(),
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
                    "chart_spec": chart_spec.model_dump(),
                },
            )
            logger.info("ToolResult created successfully")
            return tool_result

        except FileNotFoundError as e:
            logger.error(f"File not found: {args.filename}", exc_info=True)
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
                error=str(e),
                metadata={"error_type": "file_not_found"},
            )
        except pd.errors.ParserError as e:
            logger.error(f"CSV parse error for {args.filename}", exc_info=True)
            error_message = f"Failed to parse CSV file '{args.filename}': {str(e)}"
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
                error=str(e),
                metadata={"error_type": "csv_parse_error"},
            )
        except ValueError as e:
            logger.error(f"Visualization error for {args.filename}", exc_info=True)
            error_message = f"Cannot visualize data: {str(e)}"
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
                error=str(e),
                metadata={"error_type": "visualization_error"},
            )
        except Exception as e:
            logger.error(
                f"Unexpected error creating visualization for {args.filename}",
                exc_info=True,
            )
            error_message = f"Error creating visualization: {str(e)}"
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
                error=str(e),
                metadata={"error_type": "general_error"},
            )

    def _infer_column_types(self, df: pd.DataFrame) -> dict:
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
