"""
Agent implementation for the Vanna Agents framework.

This module provides the main Agent class that orchestrates the interaction
between LLM services, tools, and conversation storage.
"""

import asyncio
import uuid
from typing import TYPE_CHECKING, AsyncGenerator, List, Optional

from vanna.components import (
    UiComponent,
    SimpleTextComponent,
    RichTextComponent,
    StatusBarUpdateComponent,
    TaskTrackerUpdateComponent,
    ChatInputUpdateComponent,
    StatusCardComponent,
    CardComponent,
    Task,
)
from .config import AgentConfig
from vanna.core.storage import ConversationStore, ConversationStoreError
from vanna.core.llm import LlmService
from vanna.core.system_prompt import SystemPromptBuilder
from vanna.core.storage import Conversation, Message, REQUEST_ID_METADATA_KEY
from vanna.core.llm import LlmMessage, LlmRequest, LlmResponse
from vanna.core.tool import ToolCall, ToolContext, ToolResult, ToolSchema
from vanna.core.user import User, TRUSTED_SCHEMA_LINEAGE_METADATA_KEY
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt import DefaultSystemPromptBuilder
from vanna.core.lifecycle import LifecycleHook
from vanna.core.middleware import LlmMiddleware
from vanna.core.workflow import WorkflowHandler, DefaultWorkflowHandler
from vanna.core.recovery import ErrorRecoveryStrategy, RecoveryActionType
from vanna.core.enricher import ToolContextEnricher
from vanna.core.enhancer import LlmContextEnhancer, DefaultLlmContextEnhancer
from vanna.core.filter import ConversationFilter
from vanna.core.observability import ObservabilityProvider
from vanna.core.user.resolver import UserResolver
from vanna.core.user.request_context import RequestContext
from vanna.core.agent.config import UiFeature
from vanna.core.audit import AuditLogger
from vanna.capabilities.agent_memory import AgentMemory
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.lineage import LineageCollector
from vanna.core.tool.errors import public_tool_failure

import logging

logger = logging.getLogger(__name__)

logger.info("Loaded vanna.core.agent.agent module")

if TYPE_CHECKING:
    pass


class Agent:
    """Main agent implementation.

    The Agent class orchestrates LLM interactions, tool execution, and conversation
    management. It provides 7 extensibility points for customization:

    - lifecycle_hooks: Hook into message and tool execution lifecycle
    - llm_middlewares: Intercept and transform LLM requests/responses
    - error_recovery_strategy: Handle errors with retry logic
    - context_enrichers: Add data to tool execution context
    - llm_context_enhancer: Enhance LLM system prompts and messages with context
    - conversation_filters: Filter conversation history before LLM calls
    - observability_provider: Collect telemetry and monitoring data

    Example:
        agent = Agent(
            llm_service=AnthropicLlmService(api_key="..."),
            tool_registry=registry,
            conversation_store=store,
            lifecycle_hooks=[QuotaCheckHook()],
            llm_middlewares=[CachingMiddleware()],
            llm_context_enhancer=DefaultLlmContextEnhancer(agent_memory),
            observability_provider=LoggingProvider()
        )
    """

    def __init__(
        self,
        llm_service: LlmService,
        tool_registry: ToolRegistry,
        user_resolver: UserResolver,
        agent_memory: AgentMemory,
        conversation_store: Optional[ConversationStore] = None,
        config: AgentConfig = AgentConfig(),
        system_prompt_builder: SystemPromptBuilder = DefaultSystemPromptBuilder(),
        lifecycle_hooks: List[LifecycleHook] = [],
        llm_middlewares: List[LlmMiddleware] = [],
        workflow_handler: Optional[WorkflowHandler] = None,
        error_recovery_strategy: Optional[ErrorRecoveryStrategy] = None,
        context_enrichers: List[ToolContextEnricher] = [],
        llm_context_enhancer: Optional[LlmContextEnhancer] = None,
        conversation_filters: List[ConversationFilter] = [],
        observability_provider: Optional[ObservabilityProvider] = None,
        audit_logger: Optional[AuditLogger] = None,
        semantic_planner: Optional[SemanticFirstPlanner] = None,
    ):
        self.llm_service = llm_service
        self.tool_registry = tool_registry
        self.user_resolver = user_resolver
        self.agent_memory = agent_memory

        # Import here to avoid circular dependency
        if conversation_store is None:
            from vanna.integrations.local import MemoryConversationStore

            conversation_store = MemoryConversationStore()

        self.conversation_store = conversation_store
        self.config = config
        self.system_prompt_builder = system_prompt_builder
        self.lifecycle_hooks = lifecycle_hooks
        self.llm_middlewares = llm_middlewares

        # Use DefaultWorkflowHandler if none provided
        if workflow_handler is None:
            workflow_handler = DefaultWorkflowHandler()
        self.workflow_handler = workflow_handler

        self.error_recovery_strategy = error_recovery_strategy
        self.context_enrichers = context_enrichers

        # Use DefaultLlmContextEnhancer if none provided
        if llm_context_enhancer is None:
            llm_context_enhancer = DefaultLlmContextEnhancer(agent_memory)
        self.llm_context_enhancer = llm_context_enhancer

        self.conversation_filters = conversation_filters
        self.observability_provider = observability_provider
        self.audit_logger = audit_logger
        self.semantic_planner = semantic_planner

        # Wire audit logger into tool registry
        if self.audit_logger and self.config.audit_config.enabled:
            self.tool_registry.audit_logger = self.audit_logger
            self.tool_registry.audit_config = self.config.audit_config

        logger.info("Initialized Agent")

    async def send_message(
        self,
        request_context: RequestContext,
        message: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[UiComponent, None]:
        """
        Process a user message and yield UI components with error handling.

        Args:
            request_context: Request context for user resolution (includes metadata)
            message: User's message content
            conversation_id: Optional conversation ID; if None, creates new conversation

        Yields:
            UiComponent instances for UI updates
        """
        resolved_conversation_id = conversation_id or str(uuid.uuid4())
        trusted_request_id = request_context.metadata.get(REQUEST_ID_METADATA_KEY)
        request_id = (
            trusted_request_id[:160]
            if isinstance(trusted_request_id, str) and trusted_request_id.strip()
            else str(uuid.uuid4())
        )
        lineage_collector = LineageCollector(
            request_id=request_id,
            conversation_id=resolved_conversation_id,
        )
        schema_lineage = request_context.metadata.get(
            TRUSTED_SCHEMA_LINEAGE_METADATA_KEY,
            {},
        )
        if not isinstance(schema_lineage, dict):
            schema_lineage = {}
        lineage_collector.set_schema(
            schema_lineage.get("schema_hash"),
            schema_lineage.get("schema_snapshot_id"),
            schema_version=schema_lineage.get("schema_version"),
            schema_drifted=schema_lineage.get("schema_drift_detected", False),
        )
        emit_lineage = bool(message.strip())

        try:
            async for component in self._send_message(
                request_context,
                message,
                conversation_id=resolved_conversation_id,
                request_id=request_id,
                lineage_collector=lineage_collector,
            ):
                yield component
        except asyncio.CancelledError:
            raise
        except Exception as error:
            correlation_id = f"err_{uuid.uuid4().hex}"
            lineage_collector.set_outcome(
                "error",
                failure_code="agent_execution_failed",
            )
            lineage_collector.add_validation_check("agent_execution_failed", False)
            # Exception values can contain SQL, DSNs, or upstream credentials.
            logger.error(
                "Agent request failed correlation_id=%s error_type=%s",
                correlation_id,
                type(error).__name__,
            )

            if self.observability_provider:
                try:
                    error_span = await self.observability_provider.create_span(
                        "agent.send_message.error",
                        attributes={
                            "error_type": type(error).__name__,
                            "correlation_id": correlation_id,
                            "conversation_id": resolved_conversation_id,
                        },
                    )
                    await self.observability_provider.end_span(error_span)
                    await self.observability_provider.record_metric(
                        "agent.error.count",
                        1.0,
                        "count",
                        tags={"error_type": type(error).__name__},
                    )
                except Exception as telemetry_error:
                    logger.error(
                        "Failed to record agent error telemetry correlation_id=%s "
                        "error_type=%s",
                        correlation_id,
                        type(telemetry_error).__name__,
                    )

            error_description = (
                "An unexpected error occurred while processing your message. "
                "Please try again."
                f"\n\nCorrelation ID: {correlation_id}"
            )
            yield UiComponent(
                rich_component=StatusCardComponent(
                    title="Error Processing Message",
                    status="error",
                    description=error_description,
                    icon="⚠️",
                ),
                simple_component=SimpleTextComponent(
                    text="Error: An unexpected error occurred. Please try again. "
                    f"Correlation ID: {correlation_id}"
                ),
            )
            yield UiComponent(  # type: ignore
                rich_component=ChatInputUpdateComponent(
                    placeholder="Try again...", disabled=False
                )
            )
            if emit_lineage:
                yield self._lineage_component(lineage_collector)

            # V2 sees a normal error status. V3 converts this trusted marker
            # into its sole terminal event and does not append `done`.
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="error",
                    message="Error occurred",
                    detail="An unexpected error occurred while processing your message",
                    data={
                        "v3_terminal_error": {
                            "code": "agent_execution_failed",
                            "message": "An unexpected error occurred.",
                            "correlation_id": correlation_id,
                            "retryable": False,
                        }
                    },
                )
            )
        else:
            if emit_lineage:
                yield self._lineage_component(lineage_collector)

    async def _send_message(
        self,
        request_context: RequestContext,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        request_id: str,
        lineage_collector: LineageCollector,
    ) -> AsyncGenerator[UiComponent, None]:
        """
        Internal method to process a user message and yield UI components.

        Args:
            request_context: Request context for user resolution (includes metadata)
            message: User's message content
            conversation_id: Optional conversation ID; if None, creates new conversation

        Yields:
            UiComponent instances for UI updates
        """
        # Resolve user from request context with observability
        user_resolution_span = None
        if self.observability_provider:
            user_resolution_span = await self.observability_provider.create_span(
                "agent.user_resolution",
                attributes={"has_context": request_context is not None},
            )

        user = await self.user_resolver.resolve_user(request_context)
        lineage_collector.set_visibility(
            show_tool_names=self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_NAMES,
                user,
            ),
            show_sql=self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS,
                user,
            ),
            show_sources=self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_MEMORY_DETAILED_RESULTS,
                user,
            ),
        )

        if self.observability_provider and user_resolution_span:
            user_resolution_span.set_attribute("user_id", user.id)
            await self.observability_provider.end_span(user_resolution_span)
            if user_resolution_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.user_resolution.duration",
                    user_resolution_span.duration_ms() or 0,
                    "ms",
                )

        # Allocate or verify ownership before hooks, workflows, output, or LLM work.
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())
        conversation_span = None
        if self.observability_provider:
            conversation_span = await self.observability_provider.create_span(
                "agent.conversation.load",
                attributes={"conversation_id": conversation_id, "user_id": user.id},
            )
        (
            conversation,
            is_new_conversation,
        ) = await self.conversation_store.claim_conversation(conversation_id, user)
        if self.observability_provider and conversation_span:
            conversation_span.set_attribute("is_new", is_new_conversation)
            conversation_span.set_attribute("message_count", len(conversation.messages))
            await self.observability_provider.end_span(conversation_span)
            if conversation_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.conversation.load.duration",
                    conversation_span.duration_ms() or 0,
                    "ms",
                    tags={"is_new": str(is_new_conversation)},
                )

        # Starter UI is selected by the empty V2 message shape, not public metadata.
        is_starter_request = not message.strip()

        if is_starter_request and self.workflow_handler:
            # Handle starter UI request with observability
            starter_span = None
            if self.observability_provider:
                starter_span = await self.observability_provider.create_span(
                    "agent.workflow_handler.starter_ui", attributes={"user_id": user.id}
                )

            try:
                # Get starter UI from workflow handler
                components = await self.workflow_handler.get_starter_ui(
                    self, user, conversation
                )

                if self.observability_provider and starter_span:
                    starter_span.set_attribute("has_components", components is not None)
                    starter_span.set_attribute(
                        "component_count", len(components) if components else 0
                    )

                if components:
                    # Yield the starter UI components
                    for component in components:
                        yield component

                    # Yield finalization components
                    yield UiComponent(  # type: ignore
                        rich_component=StatusBarUpdateComponent(
                            status="idle",
                            message="Ready",
                            detail="Choose an option or type a message",
                        )
                    )
                    yield UiComponent(  # type: ignore
                        rich_component=ChatInputUpdateComponent(
                            placeholder="Ask a question...", disabled=False
                        )
                    )

                if self.observability_provider and starter_span:
                    await self.observability_provider.end_span(starter_span)
                    if starter_span.duration_ms():
                        await self.observability_provider.record_metric(
                            "agent.workflow_handler.starter_ui.duration",
                            starter_span.duration_ms() or 0,
                            "ms",
                        )

                # Save the conversation if it was newly created
                if self.config.auto_save_conversations:
                    await self.conversation_store.update_conversation_for_user(
                        conversation, user
                    )

                return  # Exit without calling LLM

            except ConversationStoreError:
                raise
            except Exception as error:
                _, failure_metadata = public_tool_failure(
                    operation="Starter workflow",
                    code="starter_workflow_failed",
                    error=error,
                )
                if self.observability_provider and starter_span:
                    starter_span.set_attribute(
                        "error_code", failure_metadata["error_type"]
                    )
                    starter_span.set_attribute("error_type", type(error).__name__)
                    starter_span.set_attribute(
                        "correlation_id", failure_metadata["correlation_id"]
                    )
                    await self.observability_provider.end_span(starter_span)
                # Fall through to normal processing on error

        # Don't process actual empty messages (that aren't starter requests)
        if not message.strip():
            return

        # Create observability span for entire message processing
        message_span = None
        if self.observability_provider:
            message_span = await self.observability_provider.create_span(
                "agent.send_message",
                attributes={
                    "user_id": user.id,
                    "conversation_id": conversation_id or "new",
                },
            )

        # Run before_message hooks with observability
        modified_message = message
        for hook in self.lifecycle_hooks:
            hook_span = None
            if self.observability_provider:
                hook_span = await self.observability_provider.create_span(
                    "agent.hook.before_message",
                    attributes={"hook": hook.__class__.__name__},
                )

            hook_result = await hook.before_message(user, modified_message)
            if hook_result is not None:
                modified_message = hook_result

            if self.observability_provider and hook_span:
                hook_span.set_attribute("modified_message", hook_result is not None)
                await self.observability_provider.end_span(hook_span)
                if hook_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.hook.duration",
                        hook_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "hook": hook.__class__.__name__,
                            "phase": "before_message",
                        },
                    )

        # Use the potentially modified message
        message = modified_message

        # Update status to working
        yield UiComponent(  # type: ignore
            rich_component=StatusBarUpdateComponent(
                status="working",
                message="Processing your request...",
                detail="Analyzing query",
            )
        )

        # Try workflow handler before adding message to conversation
        if self.workflow_handler:
            trigger_span = None
            if self.observability_provider:
                trigger_span = await self.observability_provider.create_span(
                    "agent.workflow_handler.try_handle",
                    attributes={"user_id": user.id, "conversation_id": conversation_id},
                )

            try:
                workflow_result = await self.workflow_handler.try_handle(
                    self, user, conversation, message
                )

                if self.observability_provider and trigger_span:
                    trigger_span.set_attribute(
                        "should_skip_llm", workflow_result.should_skip_llm
                    )

                if workflow_result.should_skip_llm:
                    # Workflow handled the message, short-circuit LLM
                    lineage_collector.set_outcome("workflow")
                    lineage_collector.add_validation_check("workflow_completed")

                    # Apply conversation mutation if provided
                    if workflow_result.conversation_mutation:
                        await workflow_result.conversation_mutation(conversation)

                    # Stream components
                    if workflow_result.components:
                        if isinstance(workflow_result.components, list):
                            for component in workflow_result.components:
                                yield component
                        else:
                            # AsyncGenerator
                            async for component in workflow_result.components:
                                yield component

                    # Finalize response (status bar + chat input)
                    yield UiComponent(  # type: ignore
                        rich_component=StatusBarUpdateComponent(
                            status="idle",
                            message="Workflow complete",
                            detail="Ready for next message",
                        )
                    )
                    yield UiComponent(  # type: ignore
                        rich_component=ChatInputUpdateComponent(
                            placeholder="Ask a question...", disabled=False
                        )
                    )

                    # Save conversation if auto-save enabled
                    if self.config.auto_save_conversations:
                        await self.conversation_store.update_conversation_for_user(
                            conversation, user
                        )

                    if self.observability_provider and trigger_span:
                        await self.observability_provider.end_span(trigger_span)

                    # Exit without calling LLM
                    return

            except Exception as error:
                logger.error(
                    "Workflow handler failed error_type=%s",
                    type(error).__name__,
                )
                lineage_collector.add_validation_check(
                    "workflow_handler_failed",
                    False,
                )
                if self.observability_provider and trigger_span:
                    trigger_span.set_attribute("error_type", type(error).__name__)
                    await self.observability_provider.end_span(trigger_span)
                # Fall through to normal LLM processing on error

            finally:
                if self.observability_provider and trigger_span:
                    await self.observability_provider.end_span(trigger_span)

        # Not triggered, add user message to conversation now
        conversation.add_message(
            Message(
                role="user",
                content=message,
                metadata={REQUEST_ID_METADATA_KEY: request_id},
            )
        )

        # Add initial task
        context_task = Task(
            title="Load conversation context",
            description="Reading message history and user context",
            status="pending",
        )
        yield UiComponent(  # type: ignore
            rich_component=TaskTrackerUpdateComponent.add_task(context_task)
        )

        # Collect available UI features for auditing
        ui_features_available = []
        for feature_name in self.config.ui_features.feature_group_access.keys():
            if self.config.ui_features.can_user_access_feature(feature_name, user):
                ui_features_available.append(feature_name)

        # Create context with observability provider and UI features
        context = ToolContext(
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            agent_memory=self.agent_memory,
            observability_provider=self.observability_provider,
            metadata={
                "ui_features_available": ui_features_available,
                "lineage_collector": lineage_collector,
            },
        )

        # Enrich context with additional data with observability
        for enricher in self.context_enrichers:
            enrichment_span = None
            if self.observability_provider:
                enrichment_span = await self.observability_provider.create_span(
                    "agent.context.enrichment",
                    attributes={"enricher": enricher.__class__.__name__},
                )

            context = await enricher.enrich_context(context)

            if self.observability_provider and enrichment_span:
                await self.observability_provider.end_span(enrichment_span)
                if enrichment_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.enrichment.duration",
                        enrichment_span.duration_ms() or 0,
                        "ms",
                        tags={"enricher": enricher.__class__.__name__},
                    )

        # Get available tools for user with observability
        schema_span = None
        if self.observability_provider:
            schema_span = await self.observability_provider.create_span(
                "agent.tool_schemas.fetch", attributes={"user_id": user.id}
            )

        tool_schemas = await self.tool_registry.get_schemas(user)

        if self.observability_provider and schema_span:
            schema_span.set_attribute("schema_count", len(tool_schemas))
            await self.observability_provider.end_span(schema_span)
            if schema_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.tool_schemas.duration",
                    schema_span.duration_ms() or 0,
                    "ms",
                    tags={"schema_count": str(len(tool_schemas))},
                )

        # Update task status to completed
        yield UiComponent(  # type: ignore
            rich_component=TaskTrackerUpdateComponent.update_task(
                context_task.id, status="completed"
            )
        )

        # Semantic-first planning constrains both advertised and executable tools.
        planner_decision = None
        if self.semantic_planner:
            planner_decision = await self.semantic_planner.decide(
                message=message,
                tool_schemas=tool_schemas,
                context=context,
            )
            context.metadata["semantic_planner_decision"] = {
                "route": planner_decision.route,
                "message": planner_decision.message,
                "warning_code": planner_decision.warning_code,
                "semantic_hint": planner_decision.semantic_hint.model_dump()
                if planner_decision.semantic_hint
                else None,
            }
            lineage_collector.add_validation_check(
                f"semantic_planner_route:{planner_decision.route}"
            )
            semantic_hint = planner_decision.semantic_hint
            semantic_request = semantic_hint.request if semantic_hint else None
            lineage_collector.set_semantic(
                semantic_hint.coverage if semantic_hint else "missing",
                metric_names=semantic_request.metrics if semantic_request else (),
                fallback_reason=(
                    planner_decision.message if planner_decision.warning_code else None
                ),
            )
            if planner_decision.blocked_tools or planner_decision.blocked_capabilities:
                blocked_tools = set(planner_decision.blocked_tools)
                for capability in planner_decision.blocked_capabilities:
                    blocked_tools.update(
                        await self.tool_registry.get_tool_names_by_capability(
                            capability,
                            user,
                        )
                    )
                tool_schemas = [
                    schema
                    for schema in tool_schemas
                    if schema.name not in blocked_tools
                ]
            if planner_decision.warning_code:
                yield UiComponent(  # type: ignore
                    rich_component=StatusBarUpdateComponent(
                        status="warning",
                        message="SQL fallback route",
                        detail=planner_decision.message,
                    )
                )

        context.metadata["allowed_tool_names"] = tuple(
            schema.name for schema in tool_schemas
        )

        # Build system prompt with observability
        prompt_span = None
        if self.observability_provider:
            prompt_span = await self.observability_provider.create_span(
                "agent.system_prompt.build",
                attributes={"tool_count": len(tool_schemas)},
            )

        system_prompt = await self.system_prompt_builder.build_system_prompt(
            user, tool_schemas
        )

        # Enforce semantic-first preference instruction when planner coverage exists.
        if planner_decision and planner_decision.route == "semantic_preferred":
            hint_text = planner_decision.message
            request_hint = (
                planner_decision.semantic_hint.request.model_dump()
                if planner_decision.semantic_hint
                and planner_decision.semantic_hint.request
                else None
            )
            system_prompt = (
                (system_prompt or "")
                + "\n\nSemantic-first routing hint:\n"
                + f"- {hint_text}\n"
                + (
                    f"- Suggested semantic_query args: {request_hint}\n"
                    if request_hint
                    else ""
                )
                + "- Use semantic_query; SQL execution tools are not permitted "
                "for this turn."
            )

        # Enhance system prompt with LLM context enhancer
        if self.llm_context_enhancer and system_prompt is not None:
            enhancement_span = None
            if self.observability_provider:
                enhancement_span = await self.observability_provider.create_span(
                    "agent.llm_context.enhance_system_prompt",
                    attributes={
                        "enhancer": self.llm_context_enhancer.__class__.__name__
                    },
                )

            system_prompt = await self.llm_context_enhancer.enhance_system_prompt(
                system_prompt, message, user
            )

            if self.observability_provider and enhancement_span:
                await self.observability_provider.end_span(enhancement_span)
                if enhancement_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.llm_context.enhance_system_prompt.duration",
                        enhancement_span.duration_ms() or 0,
                        "ms",
                        tags={"enhancer": self.llm_context_enhancer.__class__.__name__},
                    )

        if self.observability_provider and prompt_span:
            prompt_span.set_attribute(
                "prompt_length", len(system_prompt) if system_prompt else 0
            )
            await self.observability_provider.end_span(prompt_span)
            if prompt_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.system_prompt.duration", prompt_span.duration_ms() or 0, "ms"
                )

        # Build LLM request
        request = await self._build_llm_request(
            conversation, tool_schemas, user, system_prompt
        )

        # Process with tool loop
        tool_iterations = 0

        while tool_iterations < self.config.max_tool_iterations:
            if self.config.include_thinking_indicators and tool_iterations == 0:
                # TODO: Yield thinking indicator
                pass

            # Get LLM response
            if self.config.stream_responses:
                response = await self._handle_streaming_response(request)
            else:
                response = await self._send_llm_request(request)

            # Handle tool calls
            if response.is_tool_call():
                tool_iterations += 1

                # First, add the assistant message with tool_calls to the conversation
                # This is required for OpenAI API - tool messages must follow assistant messages with tool_calls
                assistant_message = Message(
                    role="assistant",
                    content=response.content or "",  # Ensure content is not None
                    tool_calls=response.tool_calls,
                )
                conversation.add_message(assistant_message)

                if response.content is not None:
                    # Yield any partial content from the assistant before tool execution
                    has_tool_invocation_message_in_chat = (
                        self.config.ui_features.can_user_access_feature(
                            UiFeature.UI_FEATURE_SHOW_TOOL_INVOCATION_MESSAGE_IN_CHAT,
                            user,
                        )
                    )
                    if has_tool_invocation_message_in_chat:
                        yield UiComponent(
                            rich_component=RichTextComponent(
                                content=response.content, markdown=True
                            ),
                            simple_component=SimpleTextComponent(text=response.content),
                        )

                        # Update status to executing tools
                        yield UiComponent(  # type: ignore
                            rich_component=StatusBarUpdateComponent(
                                status="working",
                                message="Executing tools...",
                                detail=f"Running {len(response.tool_calls or [])} tools",
                            )
                        )
                    else:
                        # Yield as a status update instead
                        yield UiComponent(  # type: ignore
                            rich_component=StatusBarUpdateComponent(
                                status="working", message=response.content, detail=""
                            )
                        )

                # Collect all tool results first
                tool_results = []
                for i, tool_call in enumerate(response.tool_calls or []):
                    # Add task for this tool execution
                    tool_task = Task(
                        title=f"Execute {tool_call.name}",
                        description=f"Running tool with provided arguments",
                        status="in_progress",
                    )

                    has_tool_names_access = (
                        self.config.ui_features.can_user_access_feature(
                            UiFeature.UI_FEATURE_SHOW_TOOL_NAMES, user
                        )
                    )

                    # Audit UI feature access check
                    if (
                        self.audit_logger
                        and self.config.audit_config.enabled
                        and self.config.audit_config.log_ui_feature_checks
                    ):
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
                            rich_component=TaskTrackerUpdateComponent.add_task(
                                tool_task
                            )
                        )

                    response_str = response.content

                    # Use primitive StatusCard instead of semantic ToolExecutionComponent
                    tool_status_card = StatusCardComponent(
                        title=f"Executing {tool_call.name}",
                        status="running",
                        description=f"Running tool with {len(tool_call.arguments)} arguments",
                        icon="⚙️",
                        metadata=tool_call.arguments,
                    )

                    has_tool_args_access = (
                        self.config.ui_features.can_user_access_feature(
                            UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS, user
                        )
                    )

                    # Audit UI feature access check
                    if (
                        self.audit_logger
                        and self.config.audit_config.enabled
                        and self.config.audit_config.log_ui_feature_checks
                    ):
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
                            simple_component=SimpleTextComponent(
                                text=response_str or ""
                            ),
                        )

                    # Run before_tool hooks with observability
                    tool = await self.tool_registry.get_authorized_tool_for_hooks(
                        tool_call.name,
                        context,
                    )
                    if tool:
                        for hook in self.lifecycle_hooks:
                            hook_span = None
                            if self.observability_provider:
                                hook_span = (
                                    await self.observability_provider.create_span(
                                        "agent.hook.before_tool",
                                        attributes={
                                            "hook": hook.__class__.__name__,
                                            "tool": tool_call.name,
                                        },
                                    )
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

                    # Execute tool with observability
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
                            tool_exec_span.set_attribute(
                                "error", result.error or "unknown"
                            )
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

                    # Run after_tool hooks with observability
                    if tool is not None:
                        for hook in self.lifecycle_hooks:
                            hook_span = None
                            if self.observability_provider:
                                hook_span = (
                                    await self.observability_provider.create_span(
                                        "agent.hook.after_tool",
                                        attributes={
                                            "hook": hook.__class__.__name__,
                                            "tool": tool_call.name,
                                        },
                                    )
                                )

                            modified_result = await hook.after_tool(result)
                            if modified_result is not None:
                                result = modified_result

                            if self.observability_provider and hook_span:
                                hook_span.set_attribute(
                                    "modified_result", modified_result is not None
                                )
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

                    # Update status card to show completion
                    final_status = "success" if result.success else "error"
                    final_description = (
                        f"Tool completed successfully"
                        if result.success
                        else f"Tool failed: {result.error or 'Unknown error'}"
                    )

                    has_tool_args_access_2 = (
                        self.config.ui_features.can_user_access_feature(
                            UiFeature.UI_FEATURE_SHOW_TOOL_ARGUMENTS, user
                        )
                    )

                    # Audit UI feature access check
                    if (
                        self.audit_logger
                        and self.config.audit_config.enabled
                        and self.config.audit_config.log_ui_feature_checks
                    ):
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
                            simple_component=SimpleTextComponent(
                                text=final_description
                            ),
                        )

                    has_tool_names_access_2 = (
                        self.config.ui_features.can_user_access_feature(
                            UiFeature.UI_FEATURE_SHOW_TOOL_NAMES, user
                        )
                    )

                    # Audit UI feature access check
                    if (
                        self.audit_logger
                        and self.config.audit_config.enabled
                        and self.config.audit_config.log_ui_feature_checks
                    ):
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
                        # Update tool task to completed
                        yield UiComponent(  # type: ignore
                            rich_component=TaskTrackerUpdateComponent.update_task(
                                tool_task.id,
                                status="completed",
                                detail=f"Tool {'completed successfully' if result.success else 'return an error'}",
                            )
                        )

                    # Yield tool result
                    if result.ui_component:
                        # For errors, check if user has access to see error details
                        if not result.success:
                            has_tool_error_access = (
                                self.config.ui_features.can_user_access_feature(
                                    UiFeature.UI_FEATURE_SHOW_TOOL_ERROR, user
                                )
                            )

                            # Audit UI feature access check
                            if (
                                self.audit_logger
                                and self.config.audit_config.enabled
                                and self.config.audit_config.log_ui_feature_checks
                            ):
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
                            # Success results are always shown if they exist
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

                # Add tool responses to conversation
                # For APIs that need all tool results in one message, this helps
                for tool_result in tool_results:
                    tool_response_message = Message(
                        role="tool",
                        content=tool_result["content"],
                        tool_call_id=tool_result["tool_call_id"],
                    )
                    conversation.add_message(tool_response_message)

                # Rebuild request with tool responses
                request = await self._build_llm_request(
                    conversation, tool_schemas, user, system_prompt
                )
            else:
                # Update status to idle and set completion message
                yield UiComponent(  # type: ignore
                    rich_component=StatusBarUpdateComponent(
                        status="idle",
                        message="Response complete",
                        detail="Ready for next message",
                    )
                )

                # Update chat input placeholder
                yield UiComponent(  # type: ignore
                    rich_component=ChatInputUpdateComponent(
                        placeholder="Ask a follow-up question...", disabled=False
                    )
                )

                # Yield final text response
                if response.content:
                    # Add assistant response to conversation
                    conversation.add_message(
                        Message(role="assistant", content=response.content)
                    )
                    yield UiComponent(
                        rich_component=RichTextComponent(
                            content=response.content, markdown=True
                        ),
                        simple_component=SimpleTextComponent(text=response.content),
                    )
                break

        # Check if we hit the tool iteration limit
        if tool_iterations >= self.config.max_tool_iterations:
            lineage_collector.set_outcome("tool_limit")
            lineage_collector.add_validation_check("tool_limit_reached", False)
            # The loop exited due to hitting the limit, not due to a natural completion
            logger.warning(
                f"Tool iteration limit reached: {tool_iterations}/{self.config.max_tool_iterations}"
            )

            # Update status bar to show warning
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="warning",
                    message="Tool limit reached",
                    detail=f"Stopped after {tool_iterations} tool executions. The task may be incomplete.",
                )
            )

            # Provide detailed warning message to user
            warning_message = f"""⚠️ **Tool Execution Limit Reached**

The agent stopped after executing {tool_iterations} tools (the configured maximum). The task may not be fully complete.

You can:
- Ask me to continue where I left off
- Adjust the `max_tool_iterations` setting if you need more tool calls
- Break the task into smaller steps"""

            yield UiComponent(
                rich_component=RichTextComponent(
                    content=warning_message, markdown=True
                ),
                simple_component=SimpleTextComponent(
                    text=f"Tool limit reached after {tool_iterations} executions. Task may be incomplete."
                ),
            )

            # Update chat input to suggest follow-up
            yield UiComponent(  # type: ignore
                rich_component=ChatInputUpdateComponent(
                    placeholder="Continue the task or ask me something else...",
                    disabled=False,
                )
            )

        # Save conversation if configured
        if self.config.auto_save_conversations:
            save_span = None
            if self.observability_provider:
                save_span = await self.observability_provider.create_span(
                    "agent.conversation.save",
                    attributes={
                        "conversation_id": conversation_id,
                        "message_count": len(conversation.messages),
                    },
                )

            await self.conversation_store.update_conversation_for_user(
                conversation, user
            )

            if self.observability_provider and save_span:
                await self.observability_provider.end_span(save_span)
                if save_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.conversation.save.duration",
                        save_span.duration_ms() or 0,
                        "ms",
                    )

        # Run after_message hooks with observability
        for hook in self.lifecycle_hooks:
            hook_span = None
            if self.observability_provider:
                hook_span = await self.observability_provider.create_span(
                    "agent.hook.after_message",
                    attributes={"hook": hook.__class__.__name__},
                )

            await hook.after_message(conversation)

            if self.observability_provider and hook_span:
                await self.observability_provider.end_span(hook_span)
                if hook_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.hook.duration",
                        hook_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "hook": hook.__class__.__name__,
                            "phase": "after_message",
                        },
                    )

        # End observability span and record metrics
        if self.observability_provider and message_span:
            message_span.set_attribute("tool_iterations", tool_iterations)

            # Track if we hit the tool iteration limit
            hit_tool_limit = tool_iterations >= self.config.max_tool_iterations
            message_span.set_attribute("hit_tool_limit", hit_tool_limit)
            if hit_tool_limit:
                message_span.set_attribute("incomplete_response", True)
                logger.info(
                    f"Tool limit reached - marking response as potentially incomplete"
                )

            await self.observability_provider.end_span(message_span)
            if message_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.message.duration",
                    message_span.duration_ms() or 0,
                    "ms",
                    tags={"user_id": user.id, "hit_tool_limit": str(hit_tool_limit)},
                )

    @staticmethod
    def _lineage_component(lineage_collector: LineageCollector) -> UiComponent:
        """Create the V2 card carrying a trusted typed V3 lineage marker."""

        payload = lineage_collector.to_public_payload()
        return UiComponent(
            rich_component=CardComponent(
                title="Evidence and Lineage",
                content=lineage_collector.to_markdown(),
                icon="🔎",
                status="info",
                collapsible=True,
                collapsed=True,
                markdown=True,
                data={"v3_lineage": payload},
            ),
            simple_component=None,
        )

    async def get_available_tools(self, user: User) -> List[ToolSchema]:
        """Get tools available to the user."""
        return await self.tool_registry.get_schemas(user)

    async def _build_llm_request(
        self,
        conversation: Conversation,
        tool_schemas: List[ToolSchema],
        user: User,
        system_prompt: Optional[str] = None,
    ) -> LlmRequest:
        """Build LLM request from conversation and tools."""
        # Apply conversation filters with observability
        filtered_messages = conversation.messages
        for filter in self.conversation_filters:
            filter_span = None
            if self.observability_provider:
                filter_span = await self.observability_provider.create_span(
                    "agent.conversation.filter",
                    attributes={
                        "filter": filter.__class__.__name__,
                        "message_count_before": len(filtered_messages),
                    },
                )

            filtered_messages = await filter.filter_messages(filtered_messages)

            if self.observability_provider and filter_span:
                filter_span.set_attribute("message_count_after", len(filtered_messages))
                await self.observability_provider.end_span(filter_span)
                if filter_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.filter.duration",
                        filter_span.duration_ms() or 0,
                        "ms",
                        tags={"filter": filter.__class__.__name__},
                    )

        messages = []
        for msg in filtered_messages:
            llm_msg = LlmMessage(
                role=msg.role,
                content=msg.content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
            )
            messages.append(llm_msg)

        # Enhance messages with LLM context enhancer
        if self.llm_context_enhancer:
            enhancement_span = None
            if self.observability_provider:
                enhancement_span = await self.observability_provider.create_span(
                    "agent.llm_context.enhance_user_messages",
                    attributes={
                        "enhancer": self.llm_context_enhancer.__class__.__name__,
                        "message_count": len(messages),
                    },
                )

            messages = await self.llm_context_enhancer.enhance_user_messages(
                messages, user
            )

            if self.observability_provider and enhancement_span:
                enhancement_span.set_attribute("message_count_after", len(messages))
                await self.observability_provider.end_span(enhancement_span)
                if enhancement_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.llm_context.enhance_user_messages.duration",
                        enhancement_span.duration_ms() or 0,
                        "ms",
                        tags={"enhancer": self.llm_context_enhancer.__class__.__name__},
                    )

        return LlmRequest(
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            user=user,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=self.config.stream_responses,
            system_prompt=system_prompt,
        )

    async def _send_llm_request(self, request: LlmRequest) -> LlmResponse:
        """Send LLM request with middleware and observability."""
        # Apply before_llm_request middlewares with observability
        for middleware in self.llm_middlewares:
            mw_span = None
            if self.observability_provider:
                mw_span = await self.observability_provider.create_span(
                    "agent.middleware.before_llm",
                    attributes={"middleware": middleware.__class__.__name__},
                )

            request = await middleware.before_llm_request(request)

            if self.observability_provider and mw_span:
                await self.observability_provider.end_span(mw_span)
                if mw_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.middleware.duration",
                        mw_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "middleware": middleware.__class__.__name__,
                            "phase": "before_llm",
                        },
                    )

        # Create observability span for LLM call
        llm_span = None
        if self.observability_provider:
            llm_span = await self.observability_provider.create_span(
                "llm.request",
                attributes={
                    "model": getattr(self.llm_service, "model", "unknown"),
                    "stream": request.stream,
                },
            )

        # Send request
        response = await self.llm_service.send_request(request)

        # End span and record metrics
        if self.observability_provider and llm_span:
            await self.observability_provider.end_span(llm_span)
            if llm_span.duration_ms():
                await self.observability_provider.record_metric(
                    "llm.request.duration", llm_span.duration_ms() or 0, "ms"
                )

        # Apply after_llm_response middlewares with observability
        for middleware in self.llm_middlewares:
            mw_span = None
            if self.observability_provider:
                mw_span = await self.observability_provider.create_span(
                    "agent.middleware.after_llm",
                    attributes={"middleware": middleware.__class__.__name__},
                )

            response = await middleware.after_llm_response(request, response)

            if self.observability_provider and mw_span:
                await self.observability_provider.end_span(mw_span)
                if mw_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.middleware.duration",
                        mw_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "middleware": middleware.__class__.__name__,
                            "phase": "after_llm",
                        },
                    )

        return response

    async def _handle_streaming_response(self, request: LlmRequest) -> LlmResponse:
        """Handle streaming response from LLM."""
        # Apply before_llm_request middlewares with observability
        for middleware in self.llm_middlewares:
            mw_span = None
            if self.observability_provider:
                mw_span = await self.observability_provider.create_span(
                    "agent.middleware.before_llm",
                    attributes={
                        "middleware": middleware.__class__.__name__,
                        "stream": True,
                    },
                )

            request = await middleware.before_llm_request(request)

            if self.observability_provider and mw_span:
                await self.observability_provider.end_span(mw_span)
                if mw_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.middleware.duration",
                        mw_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "middleware": middleware.__class__.__name__,
                            "phase": "before_llm",
                            "stream": "true",
                        },
                    )

        accumulated_content = ""
        accumulated_tool_calls = []

        # Create span for streaming
        stream_span = None
        if self.observability_provider:
            stream_span = await self.observability_provider.create_span(
                "llm.stream",
                attributes={"model": getattr(self.llm_service, "model", "unknown")},
            )

        async for chunk in self.llm_service.stream_request(request):
            if chunk.content:
                accumulated_content += chunk.content
                # Could yield intermediate TextChunk here

            if chunk.tool_calls:
                accumulated_tool_calls.extend(chunk.tool_calls)

        # End streaming span
        if self.observability_provider and stream_span:
            stream_span.set_attribute("content_length", len(accumulated_content))
            stream_span.set_attribute("tool_call_count", len(accumulated_tool_calls))
            await self.observability_provider.end_span(stream_span)
            if stream_span.duration_ms():
                await self.observability_provider.record_metric(
                    "llm.stream.duration", stream_span.duration_ms() or 0, "ms"
                )

        response = LlmResponse(
            content=accumulated_content if accumulated_content else None,
            tool_calls=accumulated_tool_calls if accumulated_tool_calls else None,
        )

        # Apply after_llm_response middlewares with observability
        for middleware in self.llm_middlewares:
            mw_span = None
            if self.observability_provider:
                mw_span = await self.observability_provider.create_span(
                    "agent.middleware.after_llm",
                    attributes={
                        "middleware": middleware.__class__.__name__,
                        "stream": True,
                    },
                )

            response = await middleware.after_llm_response(request, response)

            if self.observability_provider and mw_span:
                await self.observability_provider.end_span(mw_span)
                if mw_span.duration_ms():
                    await self.observability_provider.record_metric(
                        "agent.middleware.duration",
                        mw_span.duration_ms() or 0,
                        "ms",
                        tags={
                            "middleware": middleware.__class__.__name__,
                            "phase": "after_llm",
                            "stream": "true",
                        },
                    )

        return response
