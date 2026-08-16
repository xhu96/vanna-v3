"""
Test for ChromaDB persistence fix.

This test verifies that ChromaDB collections can be retrieved without triggering
unnecessary embedding function initialization/model downloads.
"""

import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from vanna.capabilities.agent_memory import (
    memory_scope_for_context,
    principal_memory_scope_for_context,
)
from vanna.integrations.chromadb.agent_memory import CHROMADB_AVAILABLE
from vanna.integrations.chromadb import ChromaAgentMemory
from vanna.core.user import User
from vanna.core.tool import ToolContext


@pytest.fixture
def test_user():
    """Test user for context."""
    return User(
        id="test_user",
        username="test",
        email="test@example.com",
        group_memberships=["user"],
    )


def create_test_context(test_user, agent_memory):
    """Helper to create test context."""
    return ToolContext(
        user=test_user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
        metadata={},
    )


@pytest.mark.asyncio
async def test_chromadb_collection_retrieval_without_embedding_function(test_user):
    """
    Test that existing ChromaDB collections can be retrieved without
    initializing the embedding function (avoiding model downloads).

    This test simulates the real-world scenario where:
    1. A collection is created with an embedding function (first app run)
    2. The app restarts and retrieves the existing collection
    3. The embedding function should NOT be re-initialized on retrieval
    """
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        pytest.skip("ChromaDB not installed")

    temp_dir = tempfile.mkdtemp()

    try:
        # Session 1: Create a collection using ChromaAgentMemory (simulating first app run)
        # This will create the collection with an embedding function
        memory1 = ChromaAgentMemory(
            persist_directory=temp_dir, collection_name="test_collection"
        )

        context = create_test_context(test_user, memory1)
        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)

        # Save some memories (this will create the collection)
        # We need to add explicit embeddings to avoid model download in test environment
        collection = memory1._get_collection()
        collection.add(
            ids=["mem1", "mem2"],
            documents=["test question 1", "test question 2"],
            embeddings=[[0.1] * 384, [0.2] * 384],
            metadatas=[
                {
                    "question": "test question 1",
                    "tool_name": "test_tool",
                    "args_json": "{}",
                    "timestamp": "2024-01-01T00:00:00",
                    "success": True,
                    "memory_kind": "tool",
                    "tenant_scope": tenant_scope,
                    "principal_scope": principal_scope,
                    "user_id": test_user.id,
                    "metadata_json": "{}",
                },
                {
                    "question": "test question 2",
                    "tool_name": "test_tool",
                    "args_json": "{}",
                    "timestamp": "2024-01-01T00:01:00",
                    "success": True,
                    "memory_kind": "tool",
                    "tenant_scope": tenant_scope,
                    "principal_scope": principal_scope,
                    "user_id": test_user.id,
                    "metadata_json": "{}",
                },
            ],
        )

        # Clean up references to simulate app restart
        del collection
        del memory1

        # Session 2: Create new ChromaAgentMemory instance (simulating app restart)
        # This should retrieve the existing collection WITHOUT calling _get_embedding_function
        memory2 = ChromaAgentMemory(
            persist_directory=temp_dir, collection_name="test_collection"
        )

        # Mock _get_embedding_function to verify it's not called
        original_get_ef = memory2._get_embedding_function

        def mock_get_ef():
            pytest.fail(
                "_get_embedding_function was called when retrieving existing collection"
            )

        memory2._get_embedding_function = mock_get_ef

        # This should retrieve the existing collection without calling _get_embedding_function
        collection2 = memory2._get_collection()

        # Restore original method
        memory2._get_embedding_function = original_get_ef

        # Verify collection was retrieved successfully
        assert collection2 is not None
        assert collection2.name == "test_collection"
        assert collection2.count() == 2

        # Test that we can use public API methods on the retrieved collection
        context2 = create_test_context(test_user, memory2)
        recent = await memory2.get_recent_memories(context=context2, limit=10)
        assert len(recent) == 2
        assert recent[0].question in ["test question 1", "test question 2"]

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class FakeCollection:
    """Small dependency-free Chroma contract used for scope regression tests."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[str, dict[str, Any]]] = {}

    @classmethod
    def _matches(cls, metadata: dict[str, Any], where: Any) -> bool:
        if not where:
            return True
        if "$and" in where:
            return all(cls._matches(metadata, item) for item in where["$and"])
        if "$or" in where:
            return any(cls._matches(metadata, item) for item in where["$or"])
        return all(metadata.get(key) == value for key, value in where.items())

    def upsert(self, *, ids, documents, metadatas) -> None:
        for memory_id, document, metadata in zip(ids, documents, metadatas):
            self.records[memory_id] = (document, dict(metadata))

    def count(self) -> int:
        return len(self.records)

    def query(self, *, query_texts, n_results, where) -> dict[str, Any]:
        del query_texts
        records = [
            (memory_id, metadata)
            for memory_id, (_, metadata) in self.records.items()
            if self._matches(metadata, where)
        ][:n_results]
        return {
            "ids": [[memory_id for memory_id, _ in records]],
            "distances": [[0.0 for _ in records]],
            "metadatas": [[metadata for _, metadata in records]],
        }

    def get(self, *, ids=None, where=None) -> dict[str, Any]:
        selected = [
            (memory_id, metadata)
            for memory_id, (_, metadata) in self.records.items()
            if (ids is None or memory_id in ids) and self._matches(metadata, where)
        ]
        return {
            "ids": [memory_id for memory_id, _ in selected],
            "metadatas": [metadata for _, metadata in selected],
        }

    def delete(self, *, ids) -> None:
        for memory_id in ids:
            self.records.pop(memory_id, None)


def _fake_chroma_memory() -> ChromaAgentMemory:
    memory = object.__new__(ChromaAgentMemory)
    memory._collection = FakeCollection()
    memory._client = None
    memory._executor = ThreadPoolExecutor(max_workers=1)
    memory._embedding_function = None
    return memory


@pytest.mark.asyncio
async def test_chroma_tool_and_text_memory_are_tenant_scoped() -> None:
    memory = _fake_chroma_memory()
    tenant_a_user = User(
        id="shared-subject", metadata={"tenant_id": "tenant-a"}, authenticated=True
    )
    tenant_b_user = User(
        id="shared-subject", metadata={"tenant_id": "tenant-b"}, authenticated=True
    )
    tenant_a_other_user = User(
        id="other-subject", metadata={"tenant_id": "tenant-a"}, authenticated=True
    )
    context_a = create_test_context(tenant_a_user, memory)
    context_b = create_test_context(tenant_b_user, memory)
    context_a_other = create_test_context(tenant_a_other_user, memory)

    try:
        await memory.save_tool_usage(
            "Revenue correction",
            "run_sql",
            {"sql": "SELECT 7 AS revenue"},
            context_a,
            metadata={"patch_type": "corrective", "weight": 5.0},
        )
        text = await memory.save_text_memory("tenant-a schema secret", context_a)

        assert await memory.search_similar_usage(
            "Revenue correction", context_a, similarity_threshold=0.0
        )
        assert await memory.search_text_memories(
            "schema", context_a, similarity_threshold=0.0
        )
        assert (
            await memory.search_similar_usage(
                "Revenue correction", context_b, similarity_threshold=0.0
            )
            == []
        )
        assert (
            await memory.search_text_memories(
                "schema", context_b, similarity_threshold=0.0
            )
            == []
        )
        assert (
            await memory.search_similar_usage(
                "Revenue correction", context_a_other, similarity_threshold=0.0
            )
            == []
        )
        assert await memory.search_text_memories(
            "schema", context_a_other, similarity_threshold=0.0
        )
        assert (
            await memory.delete_by_id(context_b, next(iter(memory._collection.records)))
            is False
        )
        assert await memory.delete_text_memory(context_b, text.memory_id or "") is False
        assert await memory.clear_memories(context_b) == 0
    finally:
        memory._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_chroma_feedback_suppresses_rejected_sql_and_prioritizes_correction() -> (
    None
):
    memory = _fake_chroma_memory()
    user = User(id="alice", metadata={"tenant_id": "tenant-a"}, authenticated=True)
    context = create_test_context(user, memory)

    try:
        await memory.save_tool_usage(
            "Show revenue",
            "run_sql",
            {"sql": "SELECT wrong FROM revenue"},
            context,
        )
        await memory.save_tool_usage(
            "Show revenue",
            "run_sql",
            {"sql": "SELECT wrong FROM revenue"},
            context,
            success=False,
            metadata={
                "patch_type": "negative",
                "normalized_sql": "select wrong from revenue",
            },
        )
        await memory.save_tool_usage(
            "Monthly revenue",
            "run_sql",
            {"sql": "SELECT amount FROM revenue"},
            context,
            metadata={"patch_type": "corrective", "weight": 5.0},
        )

        results = await memory.search_similar_usage(
            "Show revenue", context, similarity_threshold=0.0
        )

        assert [item.memory.args["sql"] for item in results] == [
            "SELECT amount FROM revenue"
        ]
    finally:
        memory._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_chroma_keyed_text_memory_replaces_stale_entity_per_tenant() -> None:
    memory = _fake_chroma_memory()
    context_a = create_test_context(
        User(id="alice", metadata={"tenant_id": "tenant-a"}, authenticated=True),
        memory,
    )
    context_b = create_test_context(
        User(id="alice", metadata={"tenant_id": "tenant-b"}, authenticated=True),
        memory,
    )

    try:
        first = await memory.upsert_text_memory(
            '{"action":"upsert","entity_id":"public.orders.id"}',
            context_a,
            memory_key="schema:public.orders.id",
        )
        replacement = await memory.upsert_text_memory(
            '{"action":"tombstone","entity_id":"public.orders.id"}',
            context_a,
            memory_key="schema:public.orders.id",
        )
        other_tenant = await memory.upsert_text_memory(
            '{"action":"upsert","entity_id":"public.orders.id"}',
            context_b,
            memory_key="schema:public.orders.id",
        )

        assert first.memory_id == replacement.memory_id
        assert other_tenant.memory_id != replacement.memory_id
        tenant_a_memories = await memory.get_recent_text_memories(context_a, limit=10)
        assert [item.content for item in tenant_a_memories] == [
            '{"action":"tombstone","entity_id":"public.orders.id"}'
        ]
        assert tenant_a_memories[0].metadata == {
            "tenant_scope": memory_scope_for_context(context_a),
            "user_id": "alice",
            "memory_key": "schema:public.orders.id",
        }
    finally:
        memory._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_chromadb_collection_creation_with_embedding_function():
    """
    Test that NEW ChromaDB collections are created WITH the embedding function.
    """
    if not CHROMADB_AVAILABLE:
        pytest.skip("ChromaDB not installed")

    temp_dir = tempfile.mkdtemp()

    try:
        # Test: Create ChromaAgentMemory for a non-existent collection
        memory = ChromaAgentMemory(
            persist_directory=temp_dir, collection_name="new_collection"
        )

        # Track if _get_embedding_function was called
        get_ef_called = []
        original_get_ef = memory._get_embedding_function

        def tracking_get_ef():
            get_ef_called.append(True)
            return original_get_ef()

        memory._get_embedding_function = tracking_get_ef

        # This should create a new collection and SHOULD call _get_embedding_function
        collection = memory._get_collection()

        # Restore original
        memory._get_embedding_function = original_get_ef

        # Verify collection was created
        assert collection is not None
        assert collection.name == "new_collection"

        # Verify _get_embedding_function was called
        assert get_ef_called, (
            "_get_embedding_function should be called when creating new collection"
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    # Run tests directly
    asyncio.run(test_chromadb_collection_retrieval_without_embedding_function())
    asyncio.run(test_chromadb_collection_creation_with_embedding_function())
