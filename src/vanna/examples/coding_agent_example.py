"""Safe coding-agent example using tenant-isolated file editing tools.

The core registry intentionally exposes no Python, shell, or package-install tool.
Run reviewed output through a separately administered sandbox when execution is
required.

Usage:
  python -m vanna.examples.coding_agent_example
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

from vanna import Agent, AgentConfig, ToolCall, ToolRegistry, ToolSchema, User
from vanna.agents.basic import SimpleAgentMemory, SimpleUserResolver
from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk
from vanna.core.user import RequestContext
from vanna.tools.file_system import LocalFileSystem, create_file_system_tools

DEMO_USER = User(
    id="coding-demo",
    authenticated=True,
    username="developer",
    group_memberships=["user"],
)


class CodingLlmService(LlmService):
    """Deterministic local LLM stub that demonstrates file-tool calls."""

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        await asyncio.sleep(0.01)
        return self._build_response(request)

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        await asyncio.sleep(0.01)
        response = self._build_response(request)

        if response.tool_calls:
            yield LlmStreamChunk(tool_calls=response.tool_calls)
        if response.content:
            yield LlmStreamChunk(content=response.content)
        yield LlmStreamChunk(finish_reason=response.finish_reason)

    async def validate_tools(self, tools: list[Any]) -> list[str]:
        del tools
        return []

    def _build_response(self, request: LlmRequest) -> LlmResponse:
        last_message = request.messages[-1] if request.messages else None
        if last_message is not None and last_message.role == "tool":
            return LlmResponse(
                content=f"Completed the file operation. {last_message.content}",
                finish_reason="stop",
            )

        if last_message is not None and last_message.role == "user":
            user_message = last_message.content.lower()
            if "list files" in user_message or "show files" in user_message:
                return self._tool_response("list_files", {"directory": "."})

            if "read" in user_message:
                filename = _extract_filename(user_message)
                if filename:
                    return self._tool_response(
                        "read_file",
                        {"filename": filename},
                    )

            if "create" in user_message or "write" in user_message:
                content = (
                    "# Example Python file\n"
                    "\n"
                    "def greet(name: str) -> str:\n"
                    '    return f"Hello, {name}!"\n'
                )
                return self._tool_response(
                    "write_file",
                    {
                        "filename": "example.py",
                        "content": content,
                        "overwrite": True,
                    },
                )

            if any(word in user_message for word in ("edit", "update", "modify")):
                return self._tool_response(
                    "edit_file",
                    {
                        "filename": "example.py",
                        "edits": [
                            {
                                "start_line": 3,
                                "end_line": 4,
                                "new_content": (
                                    "def greet(name: str) -> str:\n"
                                    '    """Return a friendly greeting."""\n'
                                    '    return f"Hello, {name}! Welcome."\n'
                                ),
                            }
                        ],
                    },
                )

        return LlmResponse(
            content=(
                "I can list, read, write, and edit files in your isolated workspace."
            ),
            finish_reason="stop",
        )

    @staticmethod
    def _tool_response(name: str, arguments: dict[str, Any]) -> LlmResponse:
        return LlmResponse(
            tool_calls=[
                ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=name,
                    arguments=arguments,
                )
            ],
            finish_reason="tool_calls",
        )


def create_demo_agent() -> Agent:
    """Build a local demo whose model-reachable tools cannot execute code."""

    registry = ToolRegistry()
    file_system = LocalFileSystem("./coding_agent_data")
    for tool in create_file_system_tools(file_system):
        registry.register_local_tool(tool, access_groups=["user"])

    return Agent(
        llm_service=CodingLlmService(),
        tool_registry=registry,
        user_resolver=SimpleUserResolver(DEMO_USER),
        agent_memory=SimpleAgentMemory(),
        config=AgentConfig(
            stream_responses=True,
            include_thinking_indicators=True,
            max_tool_iterations=3,
        ),
    )


async def main() -> None:
    agent = create_demo_agent()
    schemas: list[ToolSchema] = await agent.get_available_tools(DEMO_USER)
    print(f"Available tools: {[schema.name for schema in schemas]}")

    request_context = RequestContext(metadata={"demo": True})
    conversation_id = "coding-session"
    messages = (
        "List files in this directory",
        "Create a Python file",
        "Read example.py",
        "Update the greet function",
        "Read example.py again",
    )
    for message in messages:
        print(f"\nUser: {message}")
        async for component in agent.send_message(
            request_context,
            message,
            conversation_id=conversation_id,
        ):
            simple = component.simple_component
            if simple is not None:
                print(f"Agent: {simple.model_dump_json()}")


def _extract_filename(message: str) -> Optional[str]:
    for token in message.replace("\n", " ").split():
        cleaned = token.strip("'\".,;!?")
        if "." in cleaned and not cleaned.startswith("."):
            return cleaned
    return None


if __name__ == "__main__":
    asyncio.run(main())
