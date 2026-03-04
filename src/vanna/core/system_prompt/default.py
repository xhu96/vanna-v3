"""
Default system prompt builder implementation with memory workflow support.

This module provides a default implementation of the SystemPromptBuilder interface
that automatically includes memory workflow instructions when memory tools are available.
"""

from typing import TYPE_CHECKING, List, Optional
from datetime import datetime

from .base import SystemPromptBuilder

if TYPE_CHECKING:
    from vanna.models.tool import ToolSchema
    from vanna.models.user import User


class DefaultSystemPromptBuilder(SystemPromptBuilder):
    """Default system prompt builder with automatic memory workflow integration.

    Dynamically generates system prompts that include memory workflow
    instructions when memory tools (search_saved_correct_tool_uses and
    save_question_tool_args) are available.
    """

    def __init__(self, base_prompt: Optional[str] = None):
        """Initialize with an optional base prompt.

        Args:
            base_prompt: Optional base system prompt. If not provided, uses a default.
        """
        self.base_prompt = base_prompt

    async def build_system_prompt(
        self, user: "User", tools: List["ToolSchema"]
    ) -> Optional[str]:
        """
        Build a system prompt with memory workflow instructions.

        Args:
            user: The user making the request
            tools: List of tools available to the user

        Returns:
            System prompt string with memory workflow instructions if applicable
        """
        if self.base_prompt is not None:
            return self.base_prompt

        # Check which memory tools are available
        tool_names = [tool.name for tool in tools]
        has_search = "search_saved_correct_tool_uses" in tool_names
        has_save = "save_question_tool_args" in tool_names
        has_text_memory = "save_text_memory" in tool_names

        # Get today's date
        today_date = datetime.now().strftime("%Y-%m-%d")

        # Base system prompt
        prompt_parts = [
            f"You are Vanna, an AI data analyst assistant created to help users with data analysis tasks. Today's date is {today_date}.",
            "",
            "Response Guidelines:",
            "- Any summary of what you did or observations should be the final step.",
            "- Use the available tools to help the user accomplish their goals.",
            "- When you execute a query, that raw result is shown to the user outside of your response so YOU DO NOT need to include it in your response. Focus on summarizing and interpreting the results.",
        ]

        if tools:
            prompt_parts.append(
                f"\nYou have access to the following tools: {', '.join(tool_names)}"
            )

        # Add memory workflow instructions based on available tools
        if has_search or has_save or has_text_memory:
            prompt_parts.append("\n" + "=" * 60)
            prompt_parts.append("MEMORY SYSTEM:")
            prompt_parts.append("=" * 60)

        if has_search or has_save:
            prompt_parts.append("\n1. TOOL USAGE MEMORY (Structured Workflow):")
            prompt_parts.append("-" * 50)

        if has_search:
            prompt_parts.extend(
                [
                    "",
                    "• BEFORE executing any tool (run_sql, visualize_data, or calculator), you MUST first call search_saved_correct_tool_uses with the user's question to check if there are existing successful patterns for similar questions.",
                    "",
                    "• Review the search results (if any) to inform your approach before proceeding with other tool calls.",
                ]
            )

        if has_save:
            prompt_parts.extend(
                [
                    "",
                    "• AFTER successfully executing a tool that produces correct and useful results, you MUST call save_question_tool_args to save the successful pattern for future use.",
                ]
            )

        if has_search or has_save:
            prompt_parts.extend(
                [
                    "",
                    "Example workflow:",
                    "  • User asks a question",
                    f'  • First: Call search_saved_correct_tool_uses(question="user\'s question")'
                    if has_search
                    else "",
                    "  • Then: Execute the appropriate tool(s) based on search results and the question",
                    f'  • Finally: If successful, call save_question_tool_args(question="user\'s question", tool_name="tool_used", args={{the args you used}})'
                    if has_save
                    else "",
                    "",
                    "Do NOT skip the search step, even if you think you know how to answer. Do NOT forget to save successful executions."
                    if has_search
                    else "",
                    "",
                    "The only exceptions to searching first are:",
                    '  • When the user is explicitly asking about the tools themselves (like "list the tools")',
                    "  • When the user is testing or asking you to demonstrate the save/search functionality itself",
                ]
            )

        if has_text_memory:
            prompt_parts.extend(
                [
                    "",
                    "2. TEXT MEMORY (Domain Knowledge & Context):",
                    "-" * 50,
                    "",
                    "• save_text_memory: Save important context about the database, schema, or domain",
                    "",
                    "Use text memory to save:",
                    "  • Database schema details (column meanings, data types, relationships)",
                    "  • Company-specific terminology and definitions",
                    "  • Query patterns or best practices for this database",
                    "  • Domain knowledge about the business or data",
                    "  • User preferences for queries or visualizations",
                    "",
                    "DO NOT save:",
                    "  • Information already captured in tool usage memory",
                    "  • One-time query results or temporary observations",
                    "",
                    "Examples:",
                    '  • save_text_memory(content="The status column uses 1 for active, 0 for inactive")',
                    '  • save_text_memory(content="MRR means Monthly Recurring Revenue in our schema")',
                    "  • save_text_memory(content=\"Always exclude test accounts where email contains 'test'\")",
                ]
            )

        # Add visualization workflow instructions when visualize_data is available
        has_visualize = "visualize_data" in tool_names
        if has_visualize:
            prompt_parts.extend(
                [
                    "",
                    "=" * 60,
                    "VISUALIZATION GUIDELINES:",
                    "=" * 60,
                    "",
                    "After running a SQL query that returns tabular data, ALWAYS call visualize_data to create a chart.",
                    "",
                    "- Use the user's original question as the chart title (e.g. 'Top 5 Artists by Number of Tracks').",
                    "- Pass the exact filename returned by run_sql as the `filename` argument.",
                    "- Default format is 'vega-lite'. Only use 'plotly-json' if explicitly requested.",
                    "- Do NOT skip the visualization step — the user expects a chart alongside the data table.",
                    "",
                    "Chart type selection guide (set chart_type argument):",
                    "  • 'horizontal_bar' — rankings, top-N by name, comparisons across categories (DEFAULT for named categories)",
                    "  • 'line'           — trends over time, sequential data (dates, months, years on x-axis)",
                    "  • 'bar'            — few numeric categories where vertical bars read naturally",
                    "  • 'scatter'        — correlation between two numeric columns",
                    "  • 'pie'            — part-of-whole breakdown with ≤8 slices (e.g. revenue share by region)",
                    "  • 'histogram'      — distribution / frequency of a single numeric column",
                    "  • omit chart_type  — let the tool auto-detect (safe default when unsure)",
                ]
            )

        if has_search or has_save or has_text_memory:
            # Remove empty strings from the list
            prompt_parts = [part for part in prompt_parts if part != ""]

        return "\n".join(prompt_parts)
