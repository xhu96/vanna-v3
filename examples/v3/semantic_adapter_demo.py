"""Golden path: semantic-first routing with the real FileSemanticAdapter.

The adapter loads metrics from ``semantic_model.yaml`` and runs their SQL
through an injected ``SqliteRunner``. A small SQLite database is seeded so
the example is runnable as living documentation.
"""

import os
import sqlite3
import tempfile

from vanna import Agent
from vanna.core.planner import SemanticFirstPlanner
from vanna.core.registry import ToolRegistry
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.semantic import FileSemanticAdapter
from vanna.integrations.sqlite import SqliteRunner
from vanna.tools.semantic_query import SemanticQueryTool

MODEL_PATH = os.path.join(os.path.dirname(__file__), "semantic_model.yaml")


class Resolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="semantic-user", group_memberships=["user"])


def _seed_db() -> str:
    path = os.path.join(tempfile.gettempdir(), "vanna_semantic_demo.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS sales (month TEXT, amount INTEGER)")
    conn.execute("DELETE FROM sales")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?)",
        [("2025-01", 100), ("2025-01", 50), ("2025-02", 80)],
    )
    conn.commit()
    conn.close()
    return path


def build_agent() -> Agent:
    db_path = _seed_db()
    semantic_adapter = FileSemanticAdapter(
        model_path=MODEL_PATH,
        sql_runner=SqliteRunner(database_path=db_path, read_only=True),
    )
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
