"""Statistical Analysis tools for Vanna"""

from typing import Any, Dict, List, Optional, Type, cast
import json
import pandas as pd
from scipy import stats
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.components import (
    UiComponent,
    DataFrameComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)
from vanna.capabilities.sql_runner import SqlRunner
from pydantic import BaseModel, Field

class TTestToolArgs(BaseModel):
    sql: str = Field(..., description="A SELECT SQL query returning at least 2 columns: a group column (categorical) and a value column (numeric).")
    group_column: str = Field(..., description="The name of the column containing the group labels.")
    value_column: str = Field(..., description="The name of the column containing the numeric values to test.")
    group_a_name: str = Field(..., description="The value in the group_column representing the first group.")
    group_b_name: str = Field(..., description="The value in the group_column representing the second group.")

class TTestTool(Tool[TTestToolArgs]):
    """Runs an independent t-test on two groups of data returned by a SQL query."""
    
    name = "run_t_test"
    description = "Runs an independent t-test on two groups of data to see if their averages are statistically different. Useful for A/B testing or comparing clear groups."

    def __init__(self, sql_runner: SqlRunner):
        self.sql_runner = sql_runner

    def get_args_schema(self) -> Type[TTestToolArgs]:
        return TTestToolArgs

    async def execute(self, context: ToolContext, args: TTestToolArgs) -> ToolResult:
        try:
            # We must use context for user resolver if needed, but SqlRunner handles its own args
            from vanna.capabilities.sql_runner import RunSqlToolArgs
            sql_args = RunSqlToolArgs(sql=args.sql)
            df = await self.sql_runner.run_sql(sql_args, context)

            if df.empty:
                return ToolResult(
                    success=False,
                    result_for_llm="Query executed successfully but returned no data.",
                    ui_component=UiComponent(
                        simple_component=SimpleTextComponent(text="No data returned from query"),
                    )
                )

            if args.group_column not in df.columns or args.value_column not in df.columns:
                return ToolResult(
                    success=False,
                    result_for_llm=f"Columns {args.group_column} and/or {args.value_column} not found in query results.",
                    ui_component=UiComponent(
                        simple_component=SimpleTextComponent(text="Missing columns in query result.")
                    )
                )

            # Split the data into the two groups
            df[args.value_column] = pd.to_numeric(df[args.value_column], errors='coerce')
            group_a_data = df[df[args.group_column] == args.group_a_name][args.value_column].dropna()
            group_b_data = df[df[args.group_column] == args.group_b_name][args.value_column].dropna()

            if len(group_a_data) == 0 or len(group_b_data) == 0:
                msg = f"One or both groups have no valid numeric data. Group A ({args.group_a_name}) size: {len(group_a_data)}. Group B ({args.group_b_name}) size: {len(group_b_data)}."
                return ToolResult(
                    success=False,
                    result_for_llm=msg,
                    ui_component=UiComponent(simple_component=SimpleTextComponent(text=msg))
                )

            # Run the stats test
            t_stat, p_value = stats.ttest_ind(group_a_data, group_b_data, nan_policy='omit')
            
            # Format results for the LLM
            stats_result = {
                "t_statistic": float(t_stat),
                "p_value": float(p_value),
                "group_a_mean": float(group_a_data.mean()),
                "group_a_count": int(len(group_a_data)),
                "group_b_mean": float(group_b_data.mean()),
                "group_b_count": int(len(group_b_data))
            }
            
            result_str = f"T-Test Results:\n{json.dumps(stats_result, indent=2)}\n\nPlease explain these results simply to the user (e.g. is the difference statistically significant? which group is higher?)."
            
            return ToolResult(
                success=True,
                result_for_llm=result_str,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION, 
                        level="info", 
                        message=f"Calculated T-Test between {args.group_a_name} and {args.group_b_name}"
                    ),
                    simple_component=SimpleTextComponent(text=f"Calculated T-Test: P-Value={p_value:.4f}")
                ),
                metadata=stats_result
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error running t-test: {str(e)}",
                ui_component=UiComponent(
                    simple_component=SimpleTextComponent(text=f"Error running t-test: {str(e)}")
                )
            )

class CorrelationToolArgs(BaseModel):
    sql: str = Field(..., description="A SELECT SQL query returning numeric columns to correlate.")

class CorrelationTool(Tool[CorrelationToolArgs]):
    """Runs a correlation matrix on numeric data returned by a SQL query."""
    
    name = "run_correlation"
    description = "Generates a Pearson correlation matrix for numeric columns returned by a SQL query to identify relationships between variables."

    def __init__(self, sql_runner: SqlRunner):
        self.sql_runner = sql_runner

    def get_args_schema(self) -> Type[CorrelationToolArgs]:
        return CorrelationToolArgs

    async def execute(self, context: ToolContext, args: CorrelationToolArgs) -> ToolResult:
        try:
            from vanna.capabilities.sql_runner import RunSqlToolArgs
            sql_args = RunSqlToolArgs(sql=args.sql)
            df = await self.sql_runner.run_sql(sql_args, context)

            if df.empty:
                return ToolResult(
                    success=False,
                    result_for_llm="Query executed successfully but returned no data.",
                    ui_component=UiComponent(simple_component=SimpleTextComponent(text="No data returned from query"))
                )

            # Select only numeric columns
            numeric_df = df.select_dtypes(include=['number'])
            
            if len(numeric_df.columns) < 2:
                return ToolResult(
                    success=False,
                    result_for_llm="Need at least two numeric columns to compute correlations.",
                    ui_component=UiComponent(simple_component=SimpleTextComponent(text="Not enough numeric columns."))
                )

            # Compute correlation matrix
            corr_matrix = numeric_df.corr()
            
            # Format nicely
            result_str = "Correlation Matrix:\n" + corr_matrix.to_markdown() + "\n\nPlease explain to the user which factors are most correlated (positively or negatively)."

            # UI representation (simple table mapping for now)
            corr_df_for_ui = corr_matrix.reset_index()
            # Rename for display
            corr_df_for_ui.rename(columns={"index": "Variable"}, inplace=True)
            results_data = corr_df_for_ui.to_dict("records")
            columns = corr_df_for_ui.columns.tolist()

            dataframe_component = DataFrameComponent.from_records(
                records=cast(List[Dict[str, Any]], results_data),
                title="Correlation Matrix",
                description=f"Generated correlation matrix for {len(numeric_df.columns)} numeric columns"
            )

            return ToolResult(
                success=True,
                result_for_llm=result_str,
                ui_component=UiComponent(
                    rich_component=dataframe_component,
                    simple_component=SimpleTextComponent(text="Computed correlation matrix.")
                ),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error running correlation: {str(e)}",
                ui_component=UiComponent(
                    simple_component=SimpleTextComponent(text=f"Error running correlation: {str(e)}")
                )
            )
