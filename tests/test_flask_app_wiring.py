import pytest
from app.flask.app import VannaFlaskServer
from vanna.core import Agent
from vanna.integrations.mock import MockLlmService
from vanna.core.registry import ToolRegistry
from vanna.core.user import UserResolver
from vanna.core.user.request_context import RequestContext
from vanna.core.user import User
from vanna.integrations.local import MemoryConversationStore
from vanna.infrastructure.agent_memory import AgentMemory
from vanna.infrastructure.agent_memory.models import TextMemory

class MockAgentMemory(AgentMemory):
    def __init__(self):
        self.text_memories = []
    async def save_tool_usage(self, question, tool_name, args, context, success=True, metadata=None): pass
    async def save_text_memory(self, content, context): return TextMemory(memory_id="1", content=content, timestamp=None)
    async def search_similar_usage(self, question, context, *, limit=10, similarity_threshold=0.7, tool_name_filter=None): return []
    async def search_text_memories(self, query, context, *, limit=10, similarity_threshold=0.7): return []
    async def get_recent_memories(self, context, limit=10): return []
    async def get_recent_text_memories(self, context, limit=10): return []
    async def delete_by_id(self, context, memory_id): return False
    async def delete_text_memory(self, context, memory_id): return False
    async def clear_memories(self, context, tool_name=None, before_date=None): return 0

class MockUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="test", username="test")

@pytest.fixture
def base_agent():
    registry = ToolRegistry()
    user_resolver = MockUserResolver()
    store = MemoryConversationStore()
    memory = MockAgentMemory()
    return Agent(
        llm_service=MockLlmService(),
        tool_registry=registry,
        user_resolver=user_resolver,
        agent_memory=memory,
        conversation_store=store,
    )

def test_app_creates_no_config(base_agent):
    server = VannaFlaskServer(base_agent)
    app = server.create_app()
    assert app is not None
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200

def test_app_creates_with_personalization(base_agent):
    config = {"personalization": {}}
    server = VannaFlaskServer(base_agent, config=config)
    app = server.create_app()
    client = app.test_client()
    response = client.get("/api/v1/profile", headers={"X-User-Id": "test", "X-Tenant-Id": "test"})
    # It might return 200 or 401 depending on exact auth mocks, but it should not 404
    assert response.status_code != 404

def test_app_creates_with_skills(base_agent):
    config = {"skills": {}}
    server = VannaFlaskServer(base_agent, config=config)
    app = server.create_app()
    client = app.test_client()
    response = client.get("/api/v1/skills", headers={"X-User-Id": "test", "X-Tenant-Id": "test"})
    assert response.status_code != 404

def test_lineage_endpoint(base_agent):
    server = VannaFlaskServer(base_agent)
    app = server.create_app()
    client = app.test_client()
    response = client.get("/api/v1/lineage/latest?conversation_id=test-conv")
    assert response.status_code == 200
    assert "lineage" in response.json
