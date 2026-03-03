"""Export data tools for Vanna"""

from typing import Type
from pydantic import BaseModel, Field
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.components import (
    UiComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)
from vanna.capabilities.sql_runner import SqlRunner
from vanna.capabilities.file_system import FileSystem
from vanna.integrations.local import LocalFileSystem

class ExportToCSVToolArgs(BaseModel):
    sql: str = Field(..., description="The SELECT SQL query that produces the data to export.")
    filename: str = Field(..., description="The name of the CSV file to export to, ending in .csv")

class ExportToCSVTool(Tool[ExportToCSVToolArgs]):
    """Runs a query and exports it to a CSV file."""
    
    name = "export_to_csv"
    description = "Exports the results of a SQL query to a local CSV file. Useful for creating data extracts for the user."

    def __init__(self, sql_runner: SqlRunner, file_system: FileSystem = None):
        self.sql_runner = sql_runner
        self.file_system = file_system or LocalFileSystem()

    def get_args_schema(self) -> Type[ExportToCSVToolArgs]:
        return ExportToCSVToolArgs

    async def execute(self, context: ToolContext, args: ExportToCSVToolArgs) -> ToolResult:
        try:
            from vanna.capabilities.sql_runner import RunSqlToolArgs
            sql_args = RunSqlToolArgs(sql=args.sql)
            df = await self.sql_runner.run_sql(sql_args, context)

            if df.empty:
                return ToolResult(
                    success=False,
                    result_for_llm="Query executed successfully but returned no data to export.",
                    ui_component=UiComponent(simple_component=SimpleTextComponent(text="No data returned from query"))
                )

            # Export to csv
            csv_content = df.to_csv(index=False)
            
            # Enforce .csv suffix
            filename = args.filename if args.filename.endswith(".csv") else f"{args.filename}.csv"
            
            await self.file_system.write_file(filename, csv_content, context, overwrite=True)

            msg = f"Successfully exported {len(df)} rows to {filename}."
            return ToolResult(
                success=True,
                result_for_llm=msg,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="success",
                        message=msg
                    ),
                    simple_component=SimpleTextComponent(text=msg)
                )
            )

        except Exception as e:
            return ToolResult(
                success=False,
                result_for_llm=f"Error exporting to CSV: {str(e)}",
                ui_component=UiComponent(
                    simple_component=SimpleTextComponent(text=f"Error exporting to CSV: {str(e)}")
                )
            )
