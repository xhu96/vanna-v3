"""
Local vector database implementation of AgentMemory.

This implementation uses ChromaDB for local vector storage of tool usage patterns.
"""

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions

    try:
        from chromadb.errors import NotFoundError
    except ImportError:
        # Fallback for older ChromaDB versions that don't have chromadb.errors
        class NotFoundError(Exception):
            """Fallback NotFoundError for older ChromaDB versions."""

            pass

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

from vanna.capabilities.agent_memory import (
    AgentMemory,
    TextMemory,
    TextMemorySearchResult,
    ToolMemory,
    ToolMemorySearchResult,
    memory_scope_for_context,
    principal_memory_scope_for_context,
)
from vanna.core.tool import ToolContext


class ChromaAgentMemory(AgentMemory):
    """ChromaDB-based implementation of AgentMemory.

    This implementation uses ChromaDB's PersistentClient to store agent memories
    on disk, ensuring they persist across application restarts.

    Key Features:
    - Persistent storage: All memories are automatically saved to disk
    - Efficient retrieval: Existing collections are loaded without re-initializing
      embedding functions, avoiding unnecessary model downloads
    - Flexible embedding: Supports custom embedding functions or uses ChromaDB's
      default embedding function

    Args:
        persist_directory: Directory where ChromaDB will store its data.
                          Defaults to "./chroma_memory". Use an absolute path
                          for production deployments to ensure consistent location
                          across restarts.
        collection_name: Name of the ChromaDB collection to use. Multiple agents
                        can share the same persist_directory with different
                        collection names.
        embedding_function: Optional custom embedding function. If not provided,
                           ChromaDB's DefaultEmbeddingFunction is used (requires
                           internet connection on first use to download the model).
                           Once a collection is created, subsequent application
                           restarts will retrieve the existing collection without
                           re-downloading the model.

    Example:
        >>> from vanna.integrations.chromadb import ChromaAgentMemory
        >>> # Basic usage with defaults
        >>> memory = ChromaAgentMemory(
        ...     persist_directory="/app/data/chroma",
        ...     collection_name="my_agent_memory"
        ... )
        >>>
        >>> # With custom embedding function (e.g., for offline use)
        >>> from chromadb.utils import embedding_functions
        >>> ef = embedding_functions.SentenceTransformerEmbeddingFunction()
        >>> memory = ChromaAgentMemory(
        ...     persist_directory="/app/data/chroma",
        ...     embedding_function=ef
        ... )

    Note:
        The default embedding function downloads an ONNX model (~80MB) on first use.
        For air-gapped or offline environments, pre-download the model or provide
        a custom embedding function.

    Limitation:
        This class does not validate that an existing Chroma collection was created
        with the same embedding function as the one configured for the current
        ``ChromaAgentMemory`` instance. If you reuse a collection (same
        ``persist_directory`` and ``collection_name``) with a different embedding
        function than was originally used, queries may fail or produce incorrect
        similarity results. It is your responsibility to ensure that a given
        collection is always accessed with a consistent embedding function, or to
        implement your own validation around collection creation and reuse.
    """

    supports_tenant_isolation = True
    supports_keyed_text_memory_upsert = True
    supports_keyed_tool_memory_upsert = True
    supports_tenant_keyed_tool_memory_upsert = True

    def __init__(
        self,
        persist_directory: str = "./chroma_memory",
        collection_name: str = "tool_memories",
        embedding_function=None,
    ):
        if not CHROMADB_AVAILABLE:
            raise ImportError(
                "ChromaDB is required for ChromaAgentMemory. Install with: pip install chromadb"
            )

        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._embedding_function = embedding_function

    def _get_client(self):
        """Get or create ChromaDB client."""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
        return self._client

    def _get_embedding_function(self):
        """Get or create the embedding function.

        If no embedding function was provided during initialization,
        uses ChromaDB's default embedding function.
        """
        if self._embedding_function is None:
            # Use ChromaDB's default embedding function
            # This avoids requiring sentence-transformers as a hard dependency
            self._embedding_function = embedding_functions.DefaultEmbeddingFunction()
        return self._embedding_function

    def _get_collection(self):
        """Get or create ChromaDB collection."""
        if self._collection is None:
            client = self._get_client()
            try:
                # Try to get existing collection first
                # Don't pass embedding_function here to avoid re-instantiating/downloading it
                # For existing collections, ChromaDB uses the stored embedding function configuration
                self._collection = client.get_collection(name=self.collection_name)
            except NotFoundError:
                # Collection doesn't exist, create it with embedding function
                embedding_func = self._get_embedding_function()
                self._collection = client.create_collection(
                    name=self.collection_name,
                    embedding_function=embedding_func,
                    metadata={"description": "Tool usage memories for learning"},
                )
        return self._collection

    def _create_memory_id(self) -> str:
        """Create a unique ID for a memory."""
        import uuid

        return str(uuid.uuid4())

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.lower().split()).rstrip(";")

    @classmethod
    def _normalized_sql(
        cls, args: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Optional[str]:
        normalized = metadata.get("normalized_sql")
        if isinstance(normalized, str) and normalized:
            return normalized
        sql = args.get("sql")
        return cls._normalize(sql) if isinstance(sql, str) else None

    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a tool usage pattern."""

        await self._store_tool_usage(
            question,
            tool_name,
            args,
            context,
            success=success,
            metadata=metadata,
            tenant_wide=False,
        )

    async def _store_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        *,
        success: bool,
        metadata: Optional[Dict[str, Any]],
        tenant_wide: bool,
    ) -> None:
        """Persist a principal or explicitly tenant-visible tool memory."""

        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)
        visibility = "tenant" if tenant_wide else "principal"
        scope_identity = tenant_scope if tenant_wide else principal_scope
        scoped_metadata = dict(metadata or {})
        scoped_metadata.update(
            {
                "tenant_scope": tenant_scope,
                "principal_scope": principal_scope,
                "memory_visibility": visibility,
                "user_id": context.user.id,
            }
        )
        idempotency_key = scoped_metadata.get("idempotency_key")
        deterministic_id = None
        if (
            isinstance(idempotency_key, str)
            and 0 < len(idempotency_key) <= 256
            and not any(ord(character) < 32 for character in idempotency_key)
        ):
            encoded = (
                f"vanna-tool-memory:{visibility}:{scope_identity}:{idempotency_key}"
            ).encode("utf-8")
            deterministic_id = f"tool_{hashlib.sha256(encoded).hexdigest()}"

        def _save():
            collection = self._get_collection()

            memory_id = deterministic_id or self._create_memory_id()
            timestamp = datetime.now().isoformat()

            # ChromaDB only accepts primitive types in metadata
            # Serialize complex objects to JSON strings
            memory_data = {
                "question": question,
                "tool_name": tool_name,
                "args_json": json.dumps(args),  # Serialize to JSON string
                "timestamp": timestamp,
                "success": success,
                "memory_kind": "tool",
                "tenant_scope": tenant_scope,
                "principal_scope": principal_scope,
                "memory_visibility": visibility,
                "user_id": context.user.id,
                "metadata_json": json.dumps(scoped_metadata),
            }

            # Use question as document text for embedding
            collection.upsert(
                ids=[memory_id], documents=[question], metadatas=[memory_data]
            )

        await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def upsert_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        *,
        memory_key: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Idempotently replace one principal-scoped logical tool memory."""

        if (
            not memory_key
            or len(memory_key) > 256
            or any(ord(character) < 32 for character in memory_key)
        ):
            raise ValueError("memory_key must be a bounded printable string")
        await self.save_tool_usage(
            question,
            tool_name,
            args,
            context,
            success=success,
            metadata={**(metadata or {}), "idempotency_key": memory_key},
        )

    async def upsert_tenant_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        *,
        memory_key: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Idempotently replace one tenant-visible feedback memory."""

        if (
            not memory_key
            or len(memory_key) > 256
            or any(ord(character) < 32 for character in memory_key)
        ):
            raise ValueError("memory_key must be a bounded printable string")
        await self._store_tool_usage(
            question,
            tool_name,
            args,
            context,
            success=success,
            metadata={**(metadata or {}), "idempotency_key": memory_key},
            tenant_wide=True,
        )

    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        """Search for similar tool usage patterns."""

        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)

        def _search():
            collection = self._get_collection()

            conditions = [
                {"memory_kind": "tool"},
                {"tenant_scope": tenant_scope},
                {
                    "$or": [
                        {"principal_scope": principal_scope},
                        {"memory_visibility": "tenant"},
                    ]
                },
            ]
            if tool_name_filter:
                conditions.append({"tool_name": tool_name_filter})
            where_filter = {"$and": conditions}

            count = collection.count()
            if count == 0:
                return []
            results = collection.query(
                query_texts=[question],
                n_results=min(count, max(limit * 4, 50)),
                where=where_filter,
            )

            candidates: list[
                tuple[ToolMemory, float, float, int, str, str, Optional[str]]
            ] = []
            rejected_sql: set[str] = set()
            if not results["ids"] or not results["ids"][0]:
                return []

            for id_, distance, metadata in zip(
                results["ids"][0],
                results["distances"][0],
                results["metadatas"][0],
            ):
                similarity = min(max(0.0, 1.0 - float(distance)), 1.0)
                if similarity < similarity_threshold:
                    continue
                args = json.loads(metadata.get("args_json", "{}"))
                memory_metadata = json.loads(metadata.get("metadata_json", "{}"))
                if memory_metadata.get("active", True) is False:
                    continue
                normalized_sql = self._normalized_sql(args, memory_metadata)
                if (
                    not metadata.get("success", True)
                    and memory_metadata.get("patch_type") == "negative"
                ):
                    if normalized_sql:
                        rejected_sql.add(normalized_sql)
                    continue
                if not metadata.get("success", True):
                    continue

                weight = memory_metadata.get("weight", 1.0)
                if not isinstance(weight, (int, float)) or not math.isfinite(weight):
                    weight = 1.0
                effective = similarity * min(max(float(weight), 0.0), 10.0)
                patch_priority = int(memory_metadata.get("patch_type") == "corrective")
                memory = ToolMemory(
                    memory_id=id_,
                    question=metadata["question"],
                    tool_name=metadata["tool_name"],
                    args=args,
                    timestamp=metadata.get("timestamp"),
                    success=True,
                    metadata=memory_metadata,
                )
                candidates.append(
                    (
                        memory,
                        similarity,
                        effective,
                        patch_priority,
                        memory.timestamp or "",
                        memory.memory_id or "",
                        normalized_sql,
                    )
                )

            candidates = [item for item in candidates if item[6] not in rejected_sql]
            candidates.sort(
                key=lambda item: (item[3], item[2], item[4], item[5]), reverse=True
            )
            return [
                ToolMemorySearchResult(
                    memory=item[0], similarity_score=item[1], rank=rank
                )
                for rank, item in enumerate(candidates[:limit], start=1)
            ]

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        """Get recently added memories. Returns most recent memories first."""

        principal_scope = principal_memory_scope_for_context(context)

        def _get_recent():
            collection = self._get_collection()

            # Get all memories and sort by timestamp
            results = collection.get(
                where={
                    "$and": [
                        {"memory_kind": "tool"},
                        {"principal_scope": principal_scope},
                    ]
                }
            )

            if not results["metadatas"] or not results["ids"]:
                return []

            # Parse and sort by timestamp
            memories_with_time = []
            for i, (doc_id, metadata) in enumerate(
                zip(results["ids"], results["metadatas"])
            ):
                # Skip text memories - they have is_text_memory flag
                if metadata.get("is_text_memory"):
                    continue

                args = json.loads(metadata.get("args_json", "{}"))
                metadata_dict = json.loads(metadata.get("metadata_json", "{}"))

                # Use the ChromaDB document ID as the memory ID
                memory = ToolMemory(
                    memory_id=doc_id,
                    question=metadata["question"],
                    tool_name=metadata["tool_name"],
                    args=args,
                    timestamp=metadata.get("timestamp"),
                    success=metadata.get("success", True),
                    metadata=metadata_dict,
                )
                memories_with_time.append((memory, metadata.get("timestamp", "")))

            # Sort by timestamp descending (most recent first)
            memories_with_time.sort(key=lambda x: x[1], reverse=True)

            # Return only the memory objects, limited to the requested amount
            return [m[0] for m in memories_with_time[:limit]]

        return await asyncio.get_event_loop().run_in_executor(
            self._executor, _get_recent
        )

    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a memory by its ID. Returns True if deleted, False if not found."""

        principal_scope = principal_memory_scope_for_context(context)

        def _delete():
            collection = self._get_collection()

            # Check if the ID exists
            try:
                results = collection.get(ids=[memory_id])
                metadata = (results.get("metadatas") or [None])[0]
                if (
                    results["ids"]
                    and len(results["ids"]) > 0
                    and isinstance(metadata, dict)
                    and metadata.get("memory_kind") == "tool"
                    and metadata.get("principal_scope") == principal_scope
                ):
                    collection.delete(ids=[memory_id])
                    return True
                return False
            except Exception:
                return False

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def save_text_memory(self, content: str, context: ToolContext) -> TextMemory:
        """Save a text memory."""

        return await self._save_text_memory(content, context)

    async def upsert_text_memory(
        self,
        content: str,
        context: ToolContext,
        *,
        memory_key: str,
    ) -> TextMemory:
        """Idempotently replace one tenant-scoped logical text memory."""

        if (
            not memory_key
            or len(memory_key) > 1200
            or any(ord(character) < 32 for character in memory_key)
        ):
            raise ValueError("memory_key must be a bounded printable string")
        return await self._save_text_memory(
            content,
            context,
            memory_key=memory_key,
        )

    async def _save_text_memory(
        self,
        content: str,
        context: ToolContext,
        *,
        memory_key: Optional[str] = None,
    ) -> TextMemory:
        """Persist a random or deterministic tenant-scoped text memory."""

        tenant_scope = memory_scope_for_context(context)

        def _save():
            collection = self._get_collection()

            memory_id = (
                f"text_{hashlib.sha256(f'{tenant_scope}:{memory_key}'.encode()).hexdigest()}"
                if memory_key is not None
                else self._create_memory_id()
            )
            timestamp = datetime.now().isoformat()

            memory_data = {
                "content": content,
                "timestamp": timestamp,
                "is_text_memory": True,
                "memory_kind": "text",
                "tenant_scope": tenant_scope,
                "user_id": context.user.id,
                **({"memory_key": memory_key} if memory_key is not None else {}),
            }

            collection.upsert(
                ids=[memory_id], documents=[content], metadatas=[memory_data]
            )

            return TextMemory(
                memory_id=memory_id,
                content=content,
                timestamp=timestamp,
                metadata={
                    "tenant_scope": tenant_scope,
                    "user_id": context.user.id,
                    **({"memory_key": memory_key} if memory_key is not None else {}),
                },
            )

        return await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        """Search for similar text memories."""

        tenant_scope = memory_scope_for_context(context)

        def _search():
            collection = self._get_collection()

            where_filter = {
                "$and": [
                    {"memory_kind": "text"},
                    {"tenant_scope": tenant_scope},
                ]
            }

            results = collection.query(
                query_texts=[query], n_results=limit, where=where_filter
            )

            search_results = []
            if results["ids"] and len(results["ids"][0]) > 0:
                for i, (id_, distance, metadata) in enumerate(
                    zip(
                        results["ids"][0],
                        results["distances"][0],
                        results["metadatas"][0],
                    )
                ):
                    similarity_score = max(0, 1 - distance)

                    if similarity_score >= similarity_threshold:
                        memory = TextMemory(
                            memory_id=id_,
                            content=metadata.get("content", ""),
                            timestamp=metadata.get("timestamp"),
                            metadata={
                                "tenant_scope": metadata.get("tenant_scope"),
                                "user_id": metadata.get("user_id"),
                                **(
                                    {"memory_key": metadata.get("memory_key")}
                                    if metadata.get("memory_key") is not None
                                    else {}
                                ),
                            },
                        )

                        search_results.append(
                            TextMemorySearchResult(
                                memory=memory,
                                similarity_score=similarity_score,
                                rank=i + 1,
                            )
                        )

            return search_results

        return await asyncio.get_event_loop().run_in_executor(self._executor, _search)

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        """Get recently added text memories."""

        tenant_scope = memory_scope_for_context(context)

        def _get_recent():
            collection = self._get_collection()

            results = collection.get(
                where={
                    "$and": [
                        {"memory_kind": "text"},
                        {"tenant_scope": tenant_scope},
                    ]
                }
            )

            if not results["metadatas"] or not results["ids"]:
                return []

            memories_with_time = []
            for doc_id, metadata in zip(results["ids"], results["metadatas"]):
                memory = TextMemory(
                    memory_id=doc_id,
                    content=metadata.get("content", ""),
                    timestamp=metadata.get("timestamp"),
                    metadata={
                        "tenant_scope": metadata.get("tenant_scope"),
                        "user_id": metadata.get("user_id"),
                        **(
                            {"memory_key": metadata.get("memory_key")}
                            if metadata.get("memory_key") is not None
                            else {}
                        ),
                    },
                )
                memories_with_time.append((memory, metadata.get("timestamp", "")))

            memories_with_time.sort(key=lambda x: x[1], reverse=True)

            return [m[0] for m in memories_with_time[:limit]]

        return await asyncio.get_event_loop().run_in_executor(
            self._executor, _get_recent
        )

    async def delete_text_memory(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a text memory by its ID."""

        tenant_scope = memory_scope_for_context(context)

        def _delete():
            collection = self._get_collection()

            try:
                results = collection.get(ids=[memory_id])
                metadata = (results.get("metadatas") or [None])[0]
                if (
                    results["ids"]
                    and len(results["ids"]) > 0
                    and isinstance(metadata, dict)
                    and metadata.get("memory_kind") == "text"
                    and metadata.get("tenant_scope") == tenant_scope
                ):
                    collection.delete(ids=[memory_id])
                    return True
                return False
            except Exception:
                return False

        return await asyncio.get_event_loop().run_in_executor(self._executor, _delete)

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        """Clear stored memories."""

        tenant_scope = memory_scope_for_context(context)
        principal_scope = principal_memory_scope_for_context(context)

        def _clear():
            collection = self._get_collection()

            # Build where filter
            tool_filter: Dict[str, Any] = {
                "$and": [
                    {"memory_kind": "tool"},
                    {"principal_scope": principal_scope},
                ]
            }
            if tool_name:
                tool_filter["$and"].append({"tool_name": tool_name})

            where_filter: Dict[str, Any]
            if tool_name:
                where_filter = tool_filter
            else:
                where_filter = {
                    "$or": [
                        tool_filter,
                        {
                            "$and": [
                                {"memory_kind": "text"},
                                {"tenant_scope": tenant_scope},
                            ]
                        },
                    ]
                }

            # Get memories to delete
            results = collection.get(where=where_filter)

            if not results["ids"]:
                return 0

            ids_to_delete = []
            for i, metadata in enumerate(results["metadatas"]):
                if before_date:
                    memory_date = metadata.get("timestamp", "")
                    if memory_date and memory_date < before_date:
                        ids_to_delete.append(results["ids"][i])
                else:
                    ids_to_delete.append(results["ids"][i])

            if ids_to_delete:
                collection.delete(ids=ids_to_delete)

            return len(ids_to_delete)

        return await asyncio.get_event_loop().run_in_executor(self._executor, _clear)
