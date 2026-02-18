"""Golden path: semantic-first routing with mock adapter."""

from vanna import Agent
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.registry import ToolRegistry
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.semantic import MockSemanticAdapter
from vanna.tools.semantic_query import SemanticQueryTool


class Resolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="semantic-user", group_memberships=["user"])


def build_agent() -> Agent:
    semantic_adapter = MockSemanticAdapter()
    tools = ToolRegistry()
    tools.register_local_tool(SemanticQueryTool(semantic_adapter), ["user"])

    return Agent(
        llm_service=MockLlmService(),
        tool_registry=tools,
        user_resolver=Resolver(),
        agent_memory=DemoAgentMemory(),
        semantic_planner=SemanticFirstPlanner(semantic_adapter=semantic_adapter),
    )


if __name__ == "__main__":
    agent = build_agent()
    print("Semantic-first demo agent initialized:", type(agent).__name__)

