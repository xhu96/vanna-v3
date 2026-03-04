"""
Agent implementation for the Vanna Agents framework.

This module provides the main Agent class that orchestrates the interaction
between LLM services, tools, and conversation storage.

Architecture:
    The Agent class is a **thin coordinator** that delegates to focused modules:
    - ``LlmHandler`` — builds, sends, and streams LLM requests
    - ``ToolExecutor`` — runs tool calls with hooks, auditing, and UI updates
    - ``EvidenceEmitter`` — builds the evidence/lineage panel
"""

import traceback
import uuid
from typing import AsyncGenerator, Dict, List, Optional

from vanna.components import (
    UiComponent,
    SimpleTextComponent,
    RichTextComponent,
    StatusBarUpdateComponent,
    TaskTrackerUpdateComponent,
    ChatInputUpdateComponent,
    StatusCardComponent,
    Task,
)
from vanna.config import AgentConfig
from vanna.core.storage import ConversationStore
from vanna.core.llm import LlmService
from vanna.core.system_prompt import SystemPromptBuilder
from vanna.core.storage import Conversation, Message
from vanna.core.llm import LlmResponse
from vanna.core.tool import ToolContext, ToolSchema
from vanna.core.user import User
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt import DefaultSystemPromptBuilder
from vanna.core.lifecycle import LifecycleHook
from vanna.core.middleware import LlmMiddleware
from vanna.core.workflow import WorkflowHandler, DefaultWorkflowHandler
from vanna.core.recovery import ErrorRecoveryStrategy
from vanna.core.enricher import ToolContextEnricher
from vanna.core.enhancer import LlmContextEnhancer, DefaultLlmContextEnhancer
from vanna.core.filter import ConversationFilter
from vanna.core.observability import ObservabilityProvider
from vanna.core.user.resolver import UserResolver
from vanna.core.user.request_context import RequestContext
from vanna.config import UiFeature
from vanna.core.audit import AuditLogger
from vanna.infrastructure.agent_memory import AgentMemory
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.lineage import LineageCollector

# Decomposed sub-modules
from vanna.core.agent.tool_executor import ToolExecutor
from vanna.core.agent.llm_handler import LlmHandler
from vanna.core.agent.evidence_emitter import EvidenceEmitter

import logging

logger = logging.getLogger(__name__)


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
        config: Optional[AgentConfig] = None,
        system_prompt_builder: Optional[SystemPromptBuilder] = None,
        lifecycle_hooks: Optional[List[LifecycleHook]] = None,
        llm_middlewares: Optional[List[LlmMiddleware]] = None,
        workflow_handler: Optional[WorkflowHandler] = None,
        error_recovery_strategy: Optional[ErrorRecoveryStrategy] = None,
        context_enrichers: Optional[List[ToolContextEnricher]] = None,
        llm_context_enhancer: Optional[LlmContextEnhancer] = None,
        conversation_filters: Optional[List[ConversationFilter]] = None,
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
        # Avoid shared mutable defaults across Agent instances.
        self.config = config or AgentConfig()
        self.system_prompt_builder = system_prompt_builder or DefaultSystemPromptBuilder()
        self.lifecycle_hooks = lifecycle_hooks or []
        self.llm_middlewares = llm_middlewares or []

        # Use DefaultWorkflowHandler if none provided
        if workflow_handler is None:
            workflow_handler = DefaultWorkflowHandler()
        self.workflow_handler = workflow_handler

        self.error_recovery_strategy = error_recovery_strategy
        self.context_enrichers = context_enrichers or []

        # Use DefaultLlmContextEnhancer if none provided
        if llm_context_enhancer is None:
            llm_context_enhancer = DefaultLlmContextEnhancer(agent_memory)
        self.llm_context_enhancer = llm_context_enhancer

        self.conversation_filters = conversation_filters or []
        self.observability_provider = observability_provider
        self.audit_logger = audit_logger
        self.semantic_planner = semantic_planner

        # Wire audit logger into tool registry
        if self.audit_logger and self.config.audit_config.enabled:
            self.tool_registry.audit_logger = self.audit_logger
            self.tool_registry.audit_config = self.config.audit_config

        # Compose sub-modules
        self._llm_handler = LlmHandler(
            llm_service=self.llm_service,
            llm_middlewares=self.llm_middlewares,
            conversation_filters=self.conversation_filters,
            llm_context_enhancer=self.llm_context_enhancer,
            observability_provider=self.observability_provider,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream_responses=self.config.stream_responses,
        )

        self._tool_executor = ToolExecutor(
            tool_registry=self.tool_registry,
            lifecycle_hooks=self.lifecycle_hooks,
            config=self.config,
            observability_provider=self.observability_provider,
            audit_logger=self.audit_logger,
        )

        self._evidence_emitter = EvidenceEmitter()

        logger.info("Initialized Agent")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        try:
            # Delegate to internal method
            async for component in self._send_message(
                request_context, message, conversation_id=conversation_id
            ):
                yield component
        except Exception as e:
            async for component in self._handle_top_level_error(e, conversation_id):
                yield component

    async def get_available_tools(self, user: User) -> List[ToolSchema]:
        """Get tools available to the user."""
        return await self.tool_registry.get_schemas(user)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    async def _handle_top_level_error(
        self, e: Exception, conversation_id: Optional[str]
    ) -> AsyncGenerator[UiComponent, None]:
        """Yield error UI components and log the exception."""
        stack_trace = traceback.format_exc()
        logger.error(
            f"Error in send_message (conversation_id={conversation_id}): {e}\n{stack_trace}",
            exc_info=True,
        )

        if self.observability_provider:
            try:
                error_span = await self.observability_provider.create_span(
                    "agent.send_message.error",
                    attributes={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "conversation_id": conversation_id or "none",
                    },
                )
                await self.observability_provider.end_span(error_span)
                await self.observability_provider.record_metric(
                    "agent.error.count",
                    1.0,
                    "count",
                    tags={"error_type": type(e).__name__},
                )
            except Exception as obs_error:
                logger.error(
                    f"Failed to log error to observability provider: {obs_error}",
                    exc_info=True,
                )

        error_details = self._get_error_details(e)
        error_description = error_details["description"]

        if conversation_id:
            error_description += f"\n\nConversation ID: {conversation_id}"

        yield UiComponent(
            rich_component=StatusCardComponent(
                title=error_details["title"],
                status="error",
                description=error_description,
                icon=error_details["icon"],
            ),
            simple_component=SimpleTextComponent(
                text=f"Error: {error_details['title']}. {error_details['description']}{f' (Conversation ID: {conversation_id})' if conversation_id else ''}"
            ),
        )

        yield UiComponent(  # type: ignore
            rich_component=StatusBarUpdateComponent(
                status="error",
                message="Error occurred",
                detail="An unexpected error occurred while processing your message",
            )
        )

        yield UiComponent(  # type: ignore
            rich_component=ChatInputUpdateComponent(
                placeholder="Try again...", disabled=False
            )
        )

    def _get_error_details(self, e: Exception) -> Dict[str, str]:
        """Categorize exception and return user-friendly title and description."""
        error_msg = str(e).lower()

        if "auth" in error_msg or "api key" in error_msg or "invalid_api_key" in error_msg or "authentication" in error_msg:
            return {
                "title": "LLM Configuration Error",
                "description": f"Your LLM API key is missing or invalid. Please check your `.env` file or Settings panel.\n\nDetails: {str(e)}",
                "icon": "🔑"
            }

        if "quota" in error_msg or "billing" in error_msg or "insufficient_funds" in error_msg:
            return {
                "title": "LLM Quota Exceeded",
                "description": f"You have exceeded your LLM quota or billing limit. Please check your provider account.\n\nDetails: {str(e)}",
                "icon": "💳"
            }
            
        if "no such file" in error_msg or "database" in error_msg or "sqlite" in error_msg or "connection" in error_msg:
            return {
                "title": "Database Connection Error",
                "description": f"There was a problem accessing your database. If you recently moved your SQLite file, please update the path in Settings.\n\nDetails: {str(e)}",
                "icon": "🗄️"
            }

        return {
            "title": "Error Processing Message",
            "description": f"An unexpected error occurred while processing your message. Please try again.\n\nDeveloper Details: {str(e)}",
            "icon": "⚠️"
        }

    # ------------------------------------------------------------------
    # Core message processing
    # ------------------------------------------------------------------

    async def _send_message(
        self,
        request_context: RequestContext,
        message: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[UiComponent, None]:
        """
        Internal method to process a user message and yield UI components.
        """
        # --- Resolve user ---
        user = await self._resolve_user(request_context)

        # --- Check starter UI ---
        is_starter_request = (not message.strip()) or request_context.metadata.get(
            "starter_ui_request", False
        )

        if is_starter_request and self.workflow_handler:
            async for component in self._handle_starter_ui(user, message, conversation_id):
                yield component
            return

        if not message.strip():
            return

        # --- Start processing ---
        message_span = None
        if self.observability_provider:
            message_span = await self.observability_provider.create_span(
                "agent.send_message",
                attributes={
                    "user_id": user.id,
                    "conversation_id": conversation_id or "new",
                },
            )

        # Run before_message hooks
        message = await self._run_before_message_hooks(user, message)

        # Generate IDs
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # Update status
        yield UiComponent(  # type: ignore
            rich_component=StatusBarUpdateComponent(
                status="working",
                message="Processing your request...",
                detail="Analyzing query",
            )
        )

        # Load or create conversation
        conversation, is_new_conversation = await self._load_or_create_conversation(
            conversation_id, user
        )

        # Try workflow handler
        if self.workflow_handler:
            workflow_result = await self._try_workflow_handler(
                user, conversation, message, conversation_id
            )
            if workflow_result is not None:
                # Workflow handled it
                async for component in workflow_result:
                    yield component
                return

        # Persist new conversation before adding message
        if is_new_conversation:
            await self.conversation_store.update_conversation(conversation)

        # Add user message
        conversation.add_message(Message(role="user", content=message))

        # Context loading task
        context_task = Task(
            title="Load conversation context",
            description="Reading message history and user context",
            status="pending",
        )
        yield UiComponent(  # type: ignore
            rich_component=TaskTrackerUpdateComponent.add_task(context_task)
        )

        # Build tool context
        lineage_collector, context = self._build_tool_context(
            user, conversation_id, request_id, request_context, message
        )

        # Enrich context
        await self._enrich_context(context)

        # Get tool schemas
        tool_schemas = await self._get_tool_schemas(user)

        yield UiComponent(  # type: ignore
            rich_component=TaskTrackerUpdateComponent.update_task(
                context_task.id, status="completed"
            )
        )

        # Semantic planner
        planner_decision = await self._run_semantic_planner(
            message, tool_schemas, context, lineage_collector
        )
        if planner_decision and planner_decision.route == "sql_fallback":
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="warning",
                    message="SQL fallback route",
                    detail=planner_decision.message,
                )
            )

        # Build system prompt
        system_prompt = await self._build_system_prompt(
            user, tool_schemas, context, message, planner_decision
        )

        # Build initial LLM request
        request = await self._llm_handler.build_request(
            conversation, tool_schemas, user, system_prompt
        )

        # --- Tool loop ---
        tool_iterations = 0
        while tool_iterations < self.config.max_tool_iterations:
            if self.config.stream_responses:
                response = await self._llm_handler.handle_streaming(request)
            else:
                response = await self._llm_handler.send_request(request)

            if response.is_tool_call():
                tool_iterations += 1

                # Add assistant message with tool_calls to conversation
                assistant_message = Message(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
                conversation.add_message(assistant_message)

                # Yield partial content from assistant
                if response.content is not None:
                    async for component in self._yield_tool_invocation_content(
                        response, user
                    ):
                        yield component

                # Execute tools via ToolExecutor
                async for component in self._tool_executor.execute_tool_calls(
                    response, context, conversation, user, request_id
                ):
                    yield component

                # Get tool results from context metadata
                tool_results = context.metadata.get("_tool_results", [])

                # Add tool responses to conversation
                for tool_result in tool_results:
                    conversation.add_message(
                        Message(
                            role="tool",
                            content=tool_result["content"],
                            tool_call_id=tool_result["tool_call_id"],
                        )
                    )

                # Rebuild request
                request = await self._llm_handler.build_request(
                    conversation, tool_schemas, user, system_prompt
                )
            else:
                # Final text response
                yield UiComponent(  # type: ignore
                    rich_component=StatusBarUpdateComponent(
                        status="idle",
                        message="Response complete",
                        detail="Ready for next message",
                    )
                )
                yield UiComponent(  # type: ignore
                    rich_component=ChatInputUpdateComponent(
                        placeholder="Ask a follow-up question...", disabled=False
                    )
                )

                if response.content:
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

        # Tool iteration limit check
        if tool_iterations >= self.config.max_tool_iterations:
            async for component in self._yield_tool_limit_warning(tool_iterations):
                yield component

        # Evidence panel
        yield self._evidence_emitter.emit_evidence_panel(lineage_collector)

        # Save conversation
        if self.config.auto_save_conversations:
            await self._save_conversation(conversation, conversation_id)

        # After-message hooks
        await self._run_after_message_hooks(conversation)

        # End observability span
        if self.observability_provider and message_span:
            message_span.set_attribute("tool_iterations", tool_iterations)
            hit_tool_limit = tool_iterations >= self.config.max_tool_iterations
            message_span.set_attribute("hit_tool_limit", hit_tool_limit)
            if hit_tool_limit:
                message_span.set_attribute("incomplete_response", True)
            await self.observability_provider.end_span(message_span)
            if message_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.message.duration",
                    message_span.duration_ms() or 0,
                    "ms",
                    tags={"user_id": user.id, "hit_tool_limit": str(hit_tool_limit)},
                )

    # ------------------------------------------------------------------
    # Helper methods (extracted for readability)
    # ------------------------------------------------------------------

    async def _resolve_user(self, request_context: RequestContext) -> User:
        """Resolve user from request context with observability."""
        user_span = None
        if self.observability_provider:
            user_span = await self.observability_provider.create_span(
                "agent.user_resolution",
                attributes={"has_context": request_context is not None},
            )

        user = await self.user_resolver.resolve_user(request_context)

        if self.observability_provider and user_span:
            user_span.set_attribute("user_id", user.id)
            await self.observability_provider.end_span(user_span)
            if user_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.user_resolution.duration",
                    user_span.duration_ms() or 0,
                    "ms",
                )
        return user

    async def _handle_starter_ui(
        self, user: User, message: str, conversation_id: Optional[str]
    ) -> AsyncGenerator[UiComponent, None]:
        """Handle starter UI request."""
        starter_span = None
        if self.observability_provider:
            starter_span = await self.observability_provider.create_span(
                "agent.workflow_handler.starter_ui", attributes={"user_id": user.id}
            )

        try:
            if conversation_id is None:
                conversation_id = str(uuid.uuid4())

            conversation = await self.conversation_store.get_conversation(
                conversation_id, user
            )
            if not conversation:
                conversation = Conversation(id=conversation_id, user=user, messages=[])

            components = await self.workflow_handler.get_starter_ui(
                self, user, conversation
            )

            if self.observability_provider and starter_span:
                starter_span.set_attribute("has_components", components is not None)
                starter_span.set_attribute(
                    "component_count", len(components) if components else 0
                )

            if components:
                for component in components:
                    yield component

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

            if self.config.auto_save_conversations:
                await self.conversation_store.update_conversation(conversation)

        except Exception as e:
            logger.error(f"Error generating starter UI: {e}", exc_info=True)
            if self.observability_provider and starter_span:
                starter_span.set_attribute("error", str(e))
                await self.observability_provider.end_span(starter_span)

    async def _run_before_message_hooks(self, user: User, message: str) -> str:
        """Run before_message hooks and return the potentially modified message."""
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

        return modified_message

    async def _load_or_create_conversation(
        self, conversation_id: str, user: User
    ) -> tuple[Conversation, bool]:
        """Load existing conversation or create a new one."""
        conversation_span = None
        if self.observability_provider:
            conversation_span = await self.observability_provider.create_span(
                "agent.conversation.load",
                attributes={"conversation_id": conversation_id, "user_id": user.id},
            )

        conversation = await self.conversation_store.get_conversation(
            conversation_id, user
        )
        is_new = conversation is None

        if not conversation:
            conversation = Conversation(id=conversation_id, user=user, messages=[])

        if self.observability_provider and conversation_span:
            conversation_span.set_attribute("is_new", is_new)
            conversation_span.set_attribute("message_count", len(conversation.messages))
            await self.observability_provider.end_span(conversation_span)
            if conversation_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.conversation.load.duration",
                    conversation_span.duration_ms() or 0,
                    "ms",
                    tags={"is_new": str(is_new)},
                )

        return conversation, is_new

    async def _try_workflow_handler(
        self, user: User, conversation: Conversation, message: str,
        conversation_id: str,
    ) -> Optional[AsyncGenerator[UiComponent, None]]:
        """Try workflow handler; return generator of components if handled, else None."""
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
                async def _workflow_components() -> AsyncGenerator[UiComponent, None]:
                    if workflow_result.conversation_mutation:
                        await workflow_result.conversation_mutation(conversation)

                    if workflow_result.components:
                        if isinstance(workflow_result.components, list):
                            for component in workflow_result.components:
                                yield component
                        else:
                            async for component in workflow_result.components:
                                yield component

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

                    if self.config.auto_save_conversations:
                        await self.conversation_store.update_conversation(conversation)

                    if self.observability_provider and trigger_span:
                        await self.observability_provider.end_span(trigger_span)

                return _workflow_components()

        except Exception as e:
            logger.error(f"Error in workflow handler: {e}", exc_info=True)
            if self.observability_provider and trigger_span:
                trigger_span.set_attribute("error", str(e))
                await self.observability_provider.end_span(trigger_span)

        finally:
            if self.observability_provider and trigger_span:
                await self.observability_provider.end_span(trigger_span)

        return None

    def _build_tool_context(
        self, user: User, conversation_id: str, request_id: str,
        request_context: RequestContext, message: str,
    ) -> tuple:
        """Build LineageCollector and ToolContext."""
        ui_features_available = [
            feature_name
            for feature_name in self.config.ui_features.feature_group_access.keys()
            if self.config.ui_features.can_user_access_feature(feature_name, user)
        ]

        lineage_collector = LineageCollector()
        lineage_collector.set_schema(
            request_context.metadata.get("schema_hash"),
            request_context.metadata.get("schema_snapshot_id"),
        )

        context = ToolContext(
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            agent_memory=self.agent_memory,
            observability_provider=self.observability_provider,
            metadata={
                "ui_features_available": ui_features_available,
                "lineage_collector": lineage_collector,
                "user_message": message,
            },
        )
        return lineage_collector, context

    async def _enrich_context(self, context: ToolContext) -> None:
        """Enrich context with additional data from enrichers."""
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

    async def _get_tool_schemas(self, user: User) -> List[ToolSchema]:
        """Get tool schemas with observability."""
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

        return tool_schemas

    async def _run_semantic_planner(
        self, message: str, tool_schemas: List[ToolSchema],
        context: ToolContext, lineage_collector: LineageCollector,
    ) -> Optional[Any]:
        """Run semantic planner if available."""
        if not self.semantic_planner:
            return None

        try:
            decision = await self.semantic_planner.decide(
                message=message,
                tool_schemas=tool_schemas,
                context=context,
            )
            context.metadata["semantic_planner_decision"] = {
                "route": decision.route,
                "message": decision.message,
                "semantic_hint": decision.semantic_hint.model_dump()
                if decision.semantic_hint
                else None,
            }
            lineage_collector.add_validation_check(
                f"semantic_planner_route:{decision.route}"
            )
            return decision
        except Exception as planner_error:
            logger.warning(
                f"Semantic planner failed; continuing without planner hints: {planner_error}"
            )
            return None

    async def _build_system_prompt(
        self, user: User, tool_schemas: List[ToolSchema],
        context: ToolContext, message: str, planner_decision: Optional[Any],
    ) -> Optional[str]:
        """Build system prompt with enhancements and planner hints."""
        prompt_span = None
        if self.observability_provider:
            prompt_span = await self.observability_provider.create_span(
                "agent.system_prompt.build",
                attributes={"tool_count": len(tool_schemas)},
            )

        system_prompt = await self.system_prompt_builder.build_system_prompt(
            user, tool_schemas
        )

        # Append runtime instructions from enrichers
        prompt_appendix = context.metadata.get("system_prompt_appendix")
        if isinstance(prompt_appendix, str) and prompt_appendix.strip():
            system_prompt = (system_prompt or "") + "\n\n" + prompt_appendix.strip()

        # Semantic-first preference instruction
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
                + "- If semantic coverage is missing, fall back to SQL and surface a warning."
            )

        # Enhance with LLM context enhancer
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

        return system_prompt

    async def _yield_tool_invocation_content(
        self, response: LlmResponse, user: User,
    ) -> AsyncGenerator[UiComponent, None]:
        """Yield assistant content before tool execution."""
        has_tool_invocation_message = (
            self.config.ui_features.can_user_access_feature(
                UiFeature.UI_FEATURE_SHOW_TOOL_INVOCATION_MESSAGE_IN_CHAT, user,
            )
        )
        if has_tool_invocation_message:
            yield UiComponent(
                rich_component=RichTextComponent(
                    content=response.content, markdown=True
                ),
                simple_component=SimpleTextComponent(text=response.content),
            )
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="working",
                    message="Executing tools...",
                    detail=f"Running {len(response.tool_calls or [])} tools",
                )
            )
        else:
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="working", message=response.content, detail=""
                )
            )

    async def _yield_tool_limit_warning(
        self, tool_iterations: int,
    ) -> AsyncGenerator[UiComponent, None]:
        """Yield warning components when tool iteration limit is reached."""
        logger.warning(
            f"Tool iteration limit reached: {tool_iterations}/{self.config.max_tool_iterations}"
        )

        yield UiComponent(  # type: ignore
            rich_component=StatusBarUpdateComponent(
                status="warning",
                message="Tool limit reached",
                detail=f"Stopped after {tool_iterations} tool executions. The task may be incomplete.",
            )
        )

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

        yield UiComponent(  # type: ignore
            rich_component=ChatInputUpdateComponent(
                placeholder="Continue the task or ask me something else...",
                disabled=False,
            )
        )

    async def _save_conversation(
        self, conversation: Conversation, conversation_id: str,
    ) -> None:
        """Save conversation with observability."""
        save_span = None
        if self.observability_provider:
            save_span = await self.observability_provider.create_span(
                "agent.conversation.save",
                attributes={
                    "conversation_id": conversation_id,
                    "message_count": len(conversation.messages),
                },
            )

        await self.conversation_store.update_conversation(conversation)

        if self.observability_provider and save_span:
            await self.observability_provider.end_span(save_span)
            if save_span.duration_ms():
                await self.observability_provider.record_metric(
                    "agent.conversation.save.duration",
                    save_span.duration_ms() or 0,
                    "ms",
                )

    async def _run_after_message_hooks(self, conversation: Conversation) -> None:
        """Run after_message hooks."""
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
