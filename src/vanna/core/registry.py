"""
Tool registry for the Vanna Agents framework.

This module provides the ToolRegistry class for managing and executing tools.
"""

import time
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    FrozenSet,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

from pydantic import ValidationError as PydanticValidationError

from .tool import (
    ARBITRARY_CODE_EXECUTION_CAPABILITY,
    Tool,
    ToolCall,
    ToolContext,
    ToolRejection,
    ToolResult,
    ToolSchema,
)
from .tool.errors import public_tool_failure
from .user import User

if TYPE_CHECKING:
    from .audit import AuditLogger
    from .agent.config import AuditConfig

T = TypeVar("T")


class _LocalToolWrapper(Tool[T]):
    """Wrapper for tools with configurable access groups."""

    def __init__(self, wrapped_tool: Tool[T], access_groups: List[str]):
        self._wrapped_tool = wrapped_tool
        self._access_groups = access_groups

    @property
    def name(self) -> str:
        return self._wrapped_tool.name

    @property
    def description(self) -> str:
        return self._wrapped_tool.description

    @property
    def access_groups(self) -> List[str]:
        return self._access_groups

    @property
    def capabilities(self) -> FrozenSet[str]:
        return self._wrapped_tool.capabilities

    def get_args_schema(self) -> Type[T]:
        return self._wrapped_tool.get_args_schema()

    async def execute(self, context: ToolContext, args: T) -> ToolResult:
        return await self._wrapped_tool.execute(context, args)


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(
        self,
        audit_logger: Optional["AuditLogger"] = None,
        audit_config: Optional["AuditConfig"] = None,
    ) -> None:
        self._tools: Dict[str, Tool[Any]] = {}
        self.audit_logger = audit_logger
        if audit_config is not None:
            self.audit_config = audit_config
        else:
            from .agent.config import AuditConfig

            self.audit_config = AuditConfig()

    def register_local_tool(self, tool: Tool[Any], access_groups: List[str]) -> None:
        """Register a local tool with optional access group restrictions.

        Args:
            tool: The tool to register
            access_groups: List of groups that can access this tool.
                          If None or empty, tool is accessible to all users.
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")

        if access_groups:
            # Wrap the tool with access groups
            wrapped_tool = _LocalToolWrapper(tool, access_groups)
            self._tools[tool.name] = wrapped_tool
        else:
            # No access restrictions, register as-is
            self._tools[tool.name] = tool

    async def get_tool(self, name: str) -> Optional[Tool[Any]]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_registered_tools(self) -> tuple[Tool[Any], ...]:
        """Return immutable tool instances for startup security validation."""
        return tuple(self._tools.values())

    @staticmethod
    def _is_core_forbidden_tool(tool: Tool[Any]) -> bool:
        """Fail closed for capabilities that core V3 never exposes to models."""

        try:
            return ARBITRARY_CODE_EXECUTION_CAPABILITY in tool.capabilities
        except Exception:
            return True

    @staticmethod
    def _turn_policy_error(tool_name: str, context: ToolContext) -> Optional[str]:
        allowed_tool_names = context.metadata.get("allowed_tool_names")
        if allowed_tool_names is None:
            return None
        if not isinstance(allowed_tool_names, (list, tuple, set, frozenset)) or not all(
            isinstance(name, str) for name in allowed_tool_names
        ):
            return "Tool execution policy is invalid; execution is blocked"
        if tool_name not in allowed_tool_names:
            return f"Tool '{tool_name}' is not permitted for this turn"
        return None

    async def get_authorized_tool_for_hooks(
        self,
        tool_name: str,
        context: ToolContext,
    ) -> Optional[Tool[Any]]:
        """Resolve a tool only after turn and group policy permit side effects."""

        if self._turn_policy_error(tool_name, context) is not None:
            return None
        tool = await self.get_tool(tool_name)
        if (
            tool is None
            or self._is_core_forbidden_tool(tool)
            or not await self._validate_tool_permissions(tool, context.user)
        ):
            return None
        return tool

    async def list_tools(self) -> List[str]:
        """List registered tools that core V3 can expose."""
        return [
            tool.name
            for tool in self._tools.values()
            if not self._is_core_forbidden_tool(tool)
        ]

    async def get_tool_names_by_capability(
        self,
        capability: str,
        user: Optional[User] = None,
    ) -> List[str]:
        """List permission-visible tools in an execution capability category."""
        names: List[str] = []
        for tool in self._tools.values():
            if self._is_core_forbidden_tool(tool):
                continue
            if capability not in tool.capabilities:
                continue
            if user is None or await self._validate_tool_permissions(tool, user):
                names.append(tool.name)
        return names

    async def get_schemas(self, user: Optional[User] = None) -> List[ToolSchema]:
        """Get schemas for all tools accessible to user."""
        schemas = []
        for tool in self._tools.values():
            if self._is_core_forbidden_tool(tool):
                continue
            if user is None or await self._validate_tool_permissions(tool, user):
                schemas.append(tool.get_schema())
        return schemas

    async def _validate_tool_permissions(self, tool: Tool[Any], user: User) -> bool:
        """Validate if user has access to tool based on group membership.

        Checks for intersection between user's group memberships and tool's access groups.
        If tool has no access groups specified, it's accessible to all users.
        """
        tool_access_groups = tool.access_groups
        if not tool_access_groups:
            return True

        user_groups = set(user.group_memberships)
        tool_groups = set(tool_access_groups)
        # Grant access if any group in user.group_memberships exists in tool.access_groups
        return bool(user_groups & tool_groups)

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: User,
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Transform and validate tool arguments based on user context.

        This method allows per-user transformation of tool arguments, such as:
        - Applying row-level security (RLS) to SQL queries
        - Filtering available options based on user permissions
        - Validating required arguments are present
        - Redacting sensitive fields

        The default implementation performs no transformation (NoOp).
        Subclasses can override this method to implement custom transformation logic.

        Args:
            tool: The tool being executed
            args: Already Pydantic-validated arguments
            user: The user executing the tool
            context: Full execution context

        Returns:
            Either:
            - Transformed arguments (may be unchanged if no transformation needed)
            - ToolRejection with explanation of why args were rejected
        """
        return args  # Default: no transformation (NoOp)

    async def execute(
        self,
        tool_call: ToolCall,
        context: ToolContext,
    ) -> ToolResult:
        """Execute a tool call with validation."""
        turn_policy_error = self._turn_policy_error(tool_call.name, context)
        if turn_policy_error is not None:
            return ToolResult(
                success=False,
                result_for_llm=turn_policy_error,
                ui_component=None,
                error=turn_policy_error,
            )

        tool = await self.get_tool(tool_call.name)
        if not tool:
            msg = f"Tool '{tool_call.name}' not found"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )

        if self._is_core_forbidden_tool(tool):
            msg = "Tool execution capability is disabled in Vanna v3 core"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
                metadata={"code": "code_execution_disabled"},
            )

        # Validate group access
        if not await self._validate_tool_permissions(tool, context.user):
            msg = f"Insufficient group access for tool '{tool_call.name}'"

            # Audit access denial
            if (
                self.audit_logger
                and self.audit_config
                and self.audit_config.log_tool_access_checks
            ):
                await self.audit_logger.log_tool_access_check(
                    user=context.user,
                    tool_name=tool_call.name,
                    access_granted=False,
                    required_groups=tool.access_groups,
                    context=context,
                    reason=msg,
                )

            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )

        # Validate and parse arguments
        try:
            args_model = tool.get_args_schema()
            validated_args = args_model.model_validate(tool_call.arguments)
        except PydanticValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
                for issue in error.errors(include_input=False)
            )
            msg = f"Invalid arguments: {details}"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )
        except Exception as error:
            msg, failure_metadata = public_tool_failure(
                operation="Tool argument validation",
                code="tool_argument_validation_failed",
                error=error,
            )
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
                metadata=failure_metadata,
            )

        # Transform/validate arguments based on user context
        transform_result = await self.transform_args(
            tool=tool,
            args=validated_args,
            user=context.user,
            context=context,
        )

        if isinstance(transform_result, ToolRejection):
            return ToolResult(
                success=False,
                result_for_llm=transform_result.reason,
                ui_component=None,
                error=transform_result.reason,
            )

        # Use transformed arguments for execution
        final_args = transform_result

        # Audit successful access check
        if (
            self.audit_logger
            and self.audit_config
            and self.audit_config.log_tool_access_checks
        ):
            await self.audit_logger.log_tool_access_check(
                user=context.user,
                tool_name=tool_call.name,
                access_granted=True,
                required_groups=tool.access_groups,
                context=context,
            )

        # Audit tool invocation
        if (
            self.audit_logger
            and self.audit_config
            and self.audit_config.log_tool_invocations
        ):
            # Get UI features if available from context
            ui_features = context.metadata.get("ui_features_available", [])
            await self.audit_logger.log_tool_invocation(
                user=context.user,
                tool_call=tool_call,
                ui_features=ui_features,
                context=context,
                sanitize_parameters=self.audit_config.sanitize_tool_parameters,
            )

        # Execute tool with context-first signature
        try:
            start_time = time.perf_counter()
            result = await tool.execute(context, final_args)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Add execution time to metadata
            result.metadata["execution_time_ms"] = execution_time_ms

            lineage_collector = context.metadata.get("lineage_collector")
            if lineage_collector is not None and hasattr(
                lineage_collector, "record_tool_result"
            ):
                lineage_collector.record_tool_result(
                    tool_name=tool_call.name,
                    success=result.success,
                    metadata=result.metadata,
                    error=result.error,
                )

            # Audit tool result
            if (
                self.audit_logger
                and self.audit_config
                and self.audit_config.log_tool_results
            ):
                await self.audit_logger.log_tool_result(
                    user=context.user,
                    tool_call=tool_call,
                    result=result,
                    context=context,
                )

            return result
        except Exception as error:
            msg, failure_metadata = public_tool_failure(
                operation="Tool execution",
                code="tool_execution_failed",
                error=error,
            )
            lineage_collector = context.metadata.get("lineage_collector")
            if lineage_collector is not None and hasattr(
                lineage_collector, "record_tool_result"
            ):
                lineage_collector.record_tool_result(
                    tool_name=tool_call.name,
                    success=False,
                    metadata={"execution_time_ms": 0.0, **failure_metadata},
                    error=msg,
                )
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
                metadata=failure_metadata,
            )
