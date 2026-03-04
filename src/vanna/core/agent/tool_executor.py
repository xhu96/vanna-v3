"""
Tool executor — runs tool calls, manages hooks, auditing, and UI components.

Extracted from agent.py to isolate the tool execution loop into a focused,
testable module.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from vanna.components import (
    SimpleTextComponent,
    StatusCardComponent,
    TaskTrackerUpdateComponent,
    Task,
    UiComponent,
)
from vanna.config import AgentConfig, UiFeature
from vanna.core.audit import AuditLogger
from vanna.core.lifecycle import LifecycleHook
from vanna.core.llm import LlmResponse
from vanna.core.observability import ObservabilityProvider
from vanna.core.registry import ToolRegistry
from vanna.core.storage import Conversation
from vanna.core.tool import ToolContext
from vanna.core.user import User

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionResult:
    """Aggregated result from executing all tool calls in a single LLM response."""

    tool_results: List[Dict[str, Any]] = field(default_factory=list)


class ToolExecutor:
    """Executes tool calls from LLM responses with hooks, auditing, and UI updates.

    This class encapsulates the full tool execution loop that was previously
    inlined in ``Agent._send_message``.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        lifecycle_hooks: List[LifecycleHook],
        config: AgentConfig,
        observability_provider: Optional[ObservabilityProvider] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.tool_registry = tool_registry
        self.lifecycle_hooks = lifecycle_hooks
        self.config = config
        self.observability_provider = observability_provider
        self.audit_logger = audit_logger

    async def execute_tool_calls(
        self,
        response: LlmResponse,
        context: ToolContext,
        conversation: Conversation,
        user: User,
        request_id: str,
    ) -> AsyncGenerator[UiComponent, None]:
        """Execute all tool calls in an LLM response.

        Yields UI components for each tool's status and result. After the
        generator is exhausted, the caller should read
        ``context.metadata["_tool_results"]`` for the list of tool result
        dicts to feed back to the LLM.

        Args:
            response: The LLM response containing tool calls.
            context: The current tool context.
            conversation: The current conversation.
            user: The current user.
            request_id: The current request ID.

        Yields:
            UiComponent instances for tool status and result display.
        """
        tool_results: List[Dict[str, Any]] = []

        for i, tool_call in enumerate(response.tool_calls or []):
            # ------ Task tracker ------
            tool_task = Task(
                title=f"Execute {tool_call.name}",
                description="Running tool with provided arguments",
                status="in_progress",
            )

            has_tool_names_access = self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_NAMES, user
            )

            if self._should_audit_feature_check():
                assert self.audit_logger is not None
                await self.audit_logger.log_ui_feature_access(
                    user=user,
                    feature_name=UiFeature.UI_FEATURE_SHOW_TOOL_NAMES,
                    access_granted=has_tool_names_access,
                    required_groups=self.config.ui_features.feature_group_access.get(
                        UiFeature.UI_FEATURE_SHOW_TOOL_NAMES, []
                    ),
                    conversation_id=conversation.id,
                    request_id=request_id,
                )

            if has_tool_names_access:
                yield UiComponent(  # type: ignore
                    rich_component=TaskTrackerUpdateComponent.add_task(tool_task)
                )

            # ------ Tool invocation status card ------
            response_str = response.content

            tool_status_card = StatusCardComponent(
                title=f"Executing {tool_call.name}",
                status="running",
                description=f"Running tool with {len(tool_call.arguments)} arguments",
                icon="⚙️",
                metadata=tool_call.arguments,
            )

            has_tool_args_access = self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS, user
            )

            if self._should_audit_feature_check():
                assert self.audit_logger is not None
                await self.audit_logger.log_ui_feature_access(
                    user=user,
                    feature_name=UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS,
                    access_granted=has_tool_args_access,
                    required_groups=self.config.ui_features.feature_group_access.get(
                        UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS, []
                    ),
                    conversation_id=conversation.id,
                    request_id=request_id,
                )

            if has_tool_args_access:
                yield UiComponent(
                    rich_component=tool_status_card,
                    simple_component=SimpleTextComponent(text=response_str or ""),
                )

            # ------ Before-tool hooks ------
            tool = await self.tool_registry.get_tool(tool_call.name)
            if tool:
                for hook in self.lifecycle_hooks:
                    hook_span = None
                    if self.observability_provider:
                        hook_span = await self.observability_provider.create_span(
                            "agent.hook.before_tool",
                            attributes={
                                "hook": hook.__class__.__name__,
                                "tool": tool_call.name,
                            },
                        )
                    await hook.before_tool(tool, context)
                    if self.observability_provider and hook_span:
                        await self.observability_provider.end_span(hook_span)
                        if hook_span.duration_ms():
                            await self.observability_provider.record_metric(
                                "agent.hook.duration",
                                hook_span.duration_ms() or 0,
                                "ms",
                                tags={
                                    "hook": hook.__class__.__name__,
                                    "phase": "before_tool",
                                    "tool": tool_call.name,
                                },
                            )

            # ------ Execute tool ------
            tool_exec_span = None
            if self.observability_provider:
                tool_exec_span = await self.observability_provider.create_span(
                    "agent.tool.execute",
                    attributes={
                        "tool": tool_call.name,
                        "arg_count": len(tool_call.arguments),
                    },
                )

            result = await self.tool_registry.execute(tool_call, context)

            if self.observability_provider and tool_exec_span:
                tool_exec_span.set_attribute("success", result.success)
                if not result.success:
                    tool_exec_span.set_attribute("error", result.error or "unknown")
                await self.observability_provider.end_span(tool_exec_span)
                if tool_exec_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.tool.duration",
                        tool_exec_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "tool": tool_call.name,
                            "success": str(result.success),
                        },
                    )

            # ------ After-tool hooks ------
            for hook in self.lifecycle_hooks:
                hook_span = None
                if self.observability_provider:
                    hook_span = await self.observability_provider.create_span(
                        "agent.hook.after_tool",
                        attributes={
                            "hook": hook.__class__.__name__,
                            "tool": tool_call.name,
                        },
                    )
                modified_result = await hook.after_tool(result)
                if modified_result is not None:
                    result = modified_result
                if self.observability_provider and hook_span:
                    hook_span.set_attribute("modified_result", modified_result is not None)
                    await self.observability_provider.end_span(hook_span)
                    if hook_span.duration_ms():
                        await self.observability_provider.record_metric(
                            "agent.hook.duration",
                            hook_span.duration_ms() or 0,
                            "ms",
                            tags={
                                "hook": hook.__class__.__name__,
                                "phase": "after_tool",
                                "tool": tool_call.name,
                            },
                        )

            # ------ Completion status card ------
            final_status = "success" if result.success else "error"
            final_description = (
                "Tool completed successfully"
                if result.success
                else f"Tool failed: {result.error or 'Unknown error'}"
            )

            has_tool_args_access_2 = self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS, user
            )

            if self._should_audit_feature_check():
                assert self.audit_logger is not None
                await self.audit_logger.log_ui_feature_access(
                    user=user,
                    feature_name=UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS,
                    access_granted=has_tool_args_access_2,
                    required_groups=self.config.ui_features.feature_group_access.get(
                        UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS, []
                    ),
                    conversation_id=conversation.id,
                    request_id=request_id,
                )

            if has_tool_args_access_2:
                yield UiComponent(
                    rich_component=tool_status_card.set_status(
                        final_status, final_description
                    ),
                    simple_component=SimpleTextComponent(text=final_description),
                )

            has_tool_names_access_2 = self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_NAMES, user
            )

            if self._should_audit_feature_check():
                assert self.audit_logger is not None
                await self.audit_logger.log_ui_feature_access(
                    user=user,
                    feature_name=UiFeature.UI_FEATURE_SHOW_TOOL_NAMES,
                    access_granted=has_tool_names_access_2,
                    required_groups=self.config.ui_features.feature_group_access.get(
                        UiFeature.UI_FEATURE_SHOW_TOOL_NAMES, []
                    ),
                    conversation_id=conversation.id,
                    request_id=request_id,
                )

            if has_tool_names_access_2:
                yield UiComponent(  # type: ignore
                    rich_component=TaskTrackerUpdateComponent.update_task(
                        tool_task.id,
                        status="completed",
                        detail=f"Tool {'completed successfully' if result.success else 'return an error'}",
                    )
                )

            # ------ Yield tool result UI ------
            if result.ui_component:
                if not result.success:
                    has_tool_error_access = (
                        self.config.ui_features.can_user_access_feature(
                            UiFeature.UI_FEATURE_SHOW_TOOL_ERROR, user
                        )
                    )

                    if self._should_audit_feature_check():
                        assert self.audit_logger is not None
                        await self.audit_logger.log_ui_feature_access(
                            user=user,
                            feature_name=UiFeature.UI_FEATURE_SHOW_TOOL_ERROR,
                            access_granted=has_tool_error_access,
                            required_groups=self.config.ui_features.feature_group_access.get(
                                UiFeature.UI_FEATURE_SHOW_TOOL_ERROR, []
                            ),
                            conversation_id=conversation.id,
                            request_id=request_id,
                        )

                    if has_tool_error_access:
                        yield result.ui_component
                else:
                    yield result.ui_component

            # Collect tool result data
            tool_results.append(
                {
                    "tool_call_id": tool_call.id,
                    "content": (
                        result.result_for_llm
                        if result.success
                        else result.error or "Tool execution failed"
                    ),
                }
            )

        # Store aggregated results in context metadata for the caller
        context.metadata["_tool_results"] = tool_results

    def _should_audit_feature_check(self) -> bool:
        """Check if UI feature access should be audited."""
        return (
            self.audit_logger is not None
            and self.config.audit_config.enabled
            and self.config.audit_config.log_ui_feature_checks
        )
