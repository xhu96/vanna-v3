"""Tenant feedback, immediate memory patching, review, and export gates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import stat
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanna import Agent, AgentConfig
from vanna.agents.basic import SimpleUserResolver
from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk
from vanna.core.registry import ToolRegistry
from vanna.core.storage import REQUEST_ID_METADATA_KEY
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.local.storage import MemoryConversationStore
from vanna.evals.training_data import (
    TrainingDataValidationError,
    load_training_export,
)
from vanna.security.rls import RowFilterPolicy
from vanna.security.sql_policy import SqlPolicyViolation, SqlQueryPolicy
from vanna.services.feedback import (
    FeedbackExportLimitError,
    FeedbackMemoryCapabilityError,
    FeedbackMemoryPatchError,
    FeedbackReviewMemoryPatchError,
    FeedbackRecord,
    FeedbackRequest,
    FeedbackReviewRequest,
    FeedbackService,
)
from vanna.services.feedback_store import FeedbackStateError, SqliteFeedbackStore


def context(
    memory: DemoAgentMemory,
    *,
    tenant: str = "tenant-a",
    user_id: str = "user-a",
    groups: tuple[str, ...] = ("user",),
    conversation_id: str = "conv-1",
    request_id: str = "req-1",
) -> ToolContext:
    return ToolContext(
        user=User(
            id=user_id,
            authenticated=True,
            metadata={"tenant_id": tenant},
            group_memberships=list(groups),
        ),
        conversation_id=conversation_id,
        request_id=request_id,
        agent_memory=memory,
    )


def service(path: Path, *, policy: SqlQueryPolicy | None = None) -> FeedbackService:
    return FeedbackService(
        database_path=str(path),
        query_policy=policy or SqlQueryPolicy("postgres", require_row_policies=False),
    )


def feedback_request(**values: object) -> FeedbackRequest:
    payload: dict[str, object] = {
        "rating": "up",
        "conversation_id": "conv-1",
        "request_id": "req-1",
    }
    payload.update(values)
    return FeedbackRequest.model_validate(payload)


class RecordingLlmService(LlmService):
    def __init__(self) -> None:
        self.requests: list[LlmRequest] = []

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return LlmResponse(content="answer", finish_reason="stop")

    async def stream_request(self, request: LlmRequest):
        self.requests.append(request)
        yield LlmStreamChunk(content="answer", finish_reason="stop")

    async def validate_tools(self, tools):
        del tools
        return []


class FlakyFeedbackMemory(DemoAgentMemory):
    def __init__(self) -> None:
        super().__init__()
        self.fail_correction_once = True

    async def upsert_tenant_tool_usage(
        self,
        question,
        tool_name,
        args,
        context,
        *,
        memory_key,
        success=True,
        metadata=None,
    ):
        if (
            self.fail_correction_once
            and metadata
            and metadata.get("patch_type") == "corrective"
        ):
            self.fail_correction_once = False
            raise RuntimeError("memory backend TOP_SECRET")
        await super().upsert_tenant_tool_usage(
            question,
            tool_name,
            args,
            context,
            memory_key=memory_key,
            success=success,
            metadata=metadata,
        )


class AppendOnlyFeedbackMemory(DemoAgentMemory):
    supports_keyed_tool_memory_upsert = False
    supports_tenant_keyed_tool_memory_upsert = False


class FlakyReviewMemory(DemoAgentMemory):
    def __init__(self) -> None:
        super().__init__()
        self.fail_approval_once = True

    async def upsert_tenant_tool_usage(
        self,
        question,
        tool_name,
        args,
        context,
        *,
        memory_key,
        success=True,
        metadata=None,
    ):
        if (
            self.fail_approval_once
            and metadata
            and metadata.get("review_status") == "approved"
        ):
            self.fail_approval_once = False
            raise RuntimeError("review memory backend TOP_SECRET")
        await super().upsert_tenant_tool_usage(
            question,
            tool_name,
            args,
            context,
            memory_key=memory_key,
            success=success,
            metadata=metadata,
        )


class BlockingFeedbackMemory(DemoAgentMemory):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.feedback_id: str | None = None
        self._blocked = False

    async def upsert_tenant_tool_usage(
        self,
        question,
        tool_name,
        args,
        context,
        *,
        memory_key,
        success=True,
        metadata=None,
    ):
        if (
            not self._blocked
            and metadata
            and metadata.get("review_status") == "pending"
        ):
            self._blocked = True
            self.feedback_id = str(metadata["feedback_id"])
            self.started.set()
            await self.release.wait()
        await super().upsert_tenant_tool_usage(
            question,
            tool_name,
            args,
            context,
            memory_key=memory_key,
            success=success,
            metadata=metadata,
        )


@pytest.mark.asyncio
async def test_thumbs_down_suppresses_rejected_sql_and_correction_wins_immediately(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    user_context = context(memory)
    feedback = service(tmp_path / "feedback.sqlite3")
    rejected_sql = "SELECT * FROM invoices"
    corrected_sql = (
        "SELECT DATE_TRUNC('month', created_at), SUM(amount) FROM invoices GROUP BY 1"
    )
    await memory.save_tool_usage(
        question="What is monthly revenue?",
        tool_name="run_sql",
        args={"sql": rejected_sql},
        context=user_context,
        success=True,
    )

    started = time.perf_counter()
    result = await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="What is monthly revenue?",
            original_sql=rejected_sql,
            corrected_sql=corrected_sql,
            reason_codes=["wrong_grain"],
            conversation_id="conv-1",
            request_id="req-1",
            enqueue_for_review=True,
        ),
        user_context,
    )
    matches = await memory.search_similar_usage(
        "What is monthly revenue?",
        user_context,
        similarity_threshold=0.1,
        tool_name_filter="run_sql",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert result.patched_memories == 2
    assert result.review_queued is True
    assert matches
    assert matches[0].memory.metadata is not None
    assert matches[0].memory.metadata["patch_type"] == "corrective"
    assert all(match.memory.args["sql"] != rejected_sql for match in matches)
    assert elapsed_ms < 100, f"feedback patch visibility was {elapsed_ms:.2f} ms"


@pytest.mark.asyncio
async def test_negative_patch_alone_suppresses_same_normalized_sql(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    user_context = context(memory)
    feedback = service(tmp_path / "feedback.sqlite3")
    await memory.save_tool_usage(
        question="Show revenue",
        tool_name="run_sql",
        args={"sql": "select *   from invoices;"},
        context=user_context,
    )

    await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="Show revenue",
            original_sql="SELECT * FROM invoices",
            reason_codes=["wrong_result"],
        ),
        user_context,
    )

    assert (
        await memory.search_similar_usage(
            "Show revenue",
            user_context,
            similarity_threshold=0.1,
        )
        == []
    )


@pytest.mark.asyncio
async def test_feedback_and_memory_are_tenant_scoped_with_user_provenance(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    tenant_a = context(memory, tenant="a", user_id="alice")
    tenant_b = context(memory, tenant="b", user_id="bob")
    feedback = service(tmp_path / "feedback.sqlite3")

    result = await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="Show orders",
            original_sql="SELECT * FROM orders",
            corrected_sql="SELECT id FROM orders",
        ),
        tenant_a,
    )

    assert (
        await memory.search_similar_usage(
            "Show orders", tenant_b, similarity_threshold=0.0
        )
        == []
    )
    record = feedback.store.get("tenant:a", result.feedback_id)
    assert record is not None
    assert record.user_id == "alice"
    assert record.tenant_scope == "tenant:a"
    assert feedback.store.get("tenant:b", result.feedback_id) is None


@pytest.mark.asyncio
async def test_unreviewed_correction_is_tenant_scoped_within_tenant(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    alice = context(memory, tenant="shared", user_id="alice")
    bob = context(memory, tenant="shared", user_id="bob")
    feedback = service(tmp_path / "feedback.sqlite3")

    await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="Show revenue",
            original_sql="SELECT wrong FROM revenue",
            corrected_sql="SELECT amount FROM revenue",
        ),
        alice,
    )

    assert await memory.search_similar_usage(
        "Show revenue", alice, similarity_threshold=0.0
    )
    bob_matches = await memory.search_similar_usage(
        "Show revenue", bob, similarity_threshold=0.0
    )
    assert bob_matches
    assert bob_matches[0].memory.metadata["patch_type"] == "corrective"

    outsider = context(memory, tenant="other", user_id="mallory")
    assert (
        await memory.search_similar_usage(
            "Show revenue", outsider, similarity_threshold=0.0
        )
        == []
    )


@pytest.mark.asyncio
async def test_validated_correction_changes_the_default_agent_next_turn(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    user = User(
        id="alice",
        authenticated=True,
        metadata={"tenant_id": "tenant-a"},
        group_memberships=["user"],
    )
    conversations = MemoryConversationStore()
    llm = RecordingLlmService()
    agent = Agent(
        llm_service=llm,
        tool_registry=ToolRegistry(),
        user_resolver=SimpleUserResolver(user),
        agent_memory=memory,
        conversation_store=conversations,
        config=AgentConfig(stream_responses=False),
    )
    conversation_id = "conversation-feedback"
    first_request_id = "request-before-feedback"
    first_context = RequestContext(metadata={REQUEST_ID_METADATA_KEY: first_request_id})
    _ = [
        component
        async for component in agent.send_message(
            first_context,
            "Show revenue",
            conversation_id=conversation_id,
        )
    ]
    stored = await conversations.get_conversation(conversation_id, user)
    assert stored is not None
    assert any(
        message.metadata.get(REQUEST_ID_METADATA_KEY) == first_request_id
        for message in stored.messages
    )

    feedback = service(tmp_path / "feedback.sqlite3")
    await feedback.process_feedback(
        feedback_request(
            rating="down",
            conversation_id=conversation_id,
            request_id=first_request_id,
            question="Show revenue",
            original_sql="SELECT wrong FROM revenue",
            corrected_sql="SELECT amount FROM revenue",
        ),
        ToolContext(
            user=user,
            conversation_id=conversation_id,
            request_id=first_request_id,
            agent_memory=memory,
        ),
    )

    llm.requests.clear()
    _ = [
        component
        async for component in agent.send_message(
            RequestContext(
                metadata={REQUEST_ID_METADATA_KEY: "request-after-feedback"}
            ),
            "Show revenue",
            conversation_id=conversation_id,
        )
    ]

    assert llm.requests
    assert llm.requests[0].system_prompt is not None
    assert "Validated Corrective SQL Memory" in llm.requests[0].system_prompt
    assert "SELECT amount FROM revenue" in llm.requests[0].system_prompt


@pytest.mark.asyncio
async def test_failed_memory_patch_is_durable_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    memory = FlakyFeedbackMemory()
    user_context = context(memory)  # type: ignore[arg-type]
    feedback = service(tmp_path / "feedback.sqlite3")

    with pytest.raises(FeedbackMemoryPatchError) as exc_info:
        await feedback.process_feedback(
            feedback_request(
                rating="down",
                question="Show revenue",
                original_sql="SELECT wrong FROM revenue",
                corrected_sql="SELECT amount FROM revenue",
            ),
            user_context,
        )

    assert "TOP_SECRET" not in str(exc_info.value)
    failed = feedback.store.get("tenant:tenant-a", exc_info.value.feedback_id)
    assert failed is not None
    assert failed.planned_memory_patches == 2
    assert failed.patched_memories == 1
    assert failed.memory_patch_status == "failed"
    assert failed.memory_patch_attempts == 1
    assert failed.memory_patch_error_code == "memory_backend_error"

    retried = await feedback.retry_memory_patch(
        exc_info.value.feedback_id, user_context
    )
    applied = feedback.store.get("tenant:tenant-a", exc_info.value.feedback_id)
    memories = list(memory._memories)

    assert retried.memory_patch_status == "applied"
    assert retried.patched_memories == 2
    assert applied is not None
    assert applied.memory_patch_status == "applied"
    assert applied.memory_patch_attempts == 2
    assert applied.memory_patch_error_code is None
    assert len(memories) == 2
    assert len({item.memory_id for item in memories}) == 2
    negative = [
        item for item in memories if item.metadata.get("patch_type") == "negative"
    ]
    assert len(negative) == 1

    with pytest.raises(PermissionError):
        await feedback.retry_memory_patch(
            exc_info.value.feedback_id,
            context(memory, user_id="mallory"),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_feedback_rejects_append_only_memory_before_persistence(
    tmp_path: Path,
) -> None:
    memory = AppendOnlyFeedbackMemory()
    feedback = service(tmp_path / "feedback.sqlite3")

    with pytest.raises(FeedbackMemoryCapabilityError, match="keyed tool-memory"):
        await feedback.process_feedback(
            feedback_request(
                rating="down",
                question="Show revenue",
                original_sql="SELECT wrong FROM revenue",
            ),
            context(memory),  # type: ignore[arg-type]
        )

    assert feedback.store.list_approved("tenant:tenant-a") == []


@pytest.mark.asyncio
async def test_corrected_sql_uses_shared_read_only_and_rls_policy(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    user_context = context(memory)
    policy = SqlQueryPolicy(
        "postgres",
        row_policies=(
            RowFilterPolicy(
                column="tenant_id",
                value="tenant-a",
                tables=frozenset({"orders"}),
            ),
        ),
    )
    feedback = service(tmp_path / "feedback.sqlite3", policy=policy)

    result = await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="Show orders",
            original_sql="SELECT id FROM orders",
            corrected_sql="SELECT id FROM orders",
        ),
        user_context,
    )
    record = feedback.store.get("tenant:tenant-a", result.feedback_id)

    assert record is not None and record.correction_validated
    assert record.corrected_sql is not None
    assert "tenant_id" in record.corrected_sql
    assert "tenant-a" in record.corrected_sql


@pytest.mark.asyncio
async def test_default_feedback_policy_rejects_unscoped_correction(
    tmp_path: Path,
) -> None:
    memory = DemoAgentMemory()
    feedback = FeedbackService(database_path=str(tmp_path / "feedback.sqlite3"))

    with pytest.raises(SqlPolicyViolation, match="required tenant policies"):
        await feedback.process_feedback(
            feedback_request(
                rating="down",
                question="Show orders",
                original_sql="SELECT id FROM orders",
                corrected_sql="SELECT id FROM orders",
            ),
            context(memory),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_sql",
    [
        "DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "WITH changed AS (UPDATE orders SET amount = 0 RETURNING *) SELECT * FROM changed",
    ],
)
async def test_unsafe_corrections_are_rejected_before_write_or_patch(
    tmp_path: Path,
    unsafe_sql: str,
) -> None:
    memory = DemoAgentMemory()
    user_context = context(memory)
    feedback = service(tmp_path / "feedback.sqlite3")

    with pytest.raises(SqlPolicyViolation):
        await feedback.process_feedback(
            feedback_request(
                rating="down",
                question="Show orders",
                corrected_sql=unsafe_sql,
            ),
            user_context,
        )

    assert await memory.get_recent_memories(user_context) == []
    assert feedback.store.list_approved("tenant:tenant-a") == []


@pytest.mark.asyncio
async def test_conflicting_request_provenance_is_denied(tmp_path: Path) -> None:
    memory = DemoAgentMemory()
    feedback = service(tmp_path / "feedback.sqlite3")

    with pytest.raises(PermissionError, match="conversation"):
        await feedback.process_feedback(
            feedback_request(
                rating="up",
                conversation_id="someone-elses-conversation",
            ),
            context(memory),
        )
    with pytest.raises(PermissionError, match="request"):
        await feedback.process_feedback(
            feedback_request(rating="up", request_id="someone-elses-request"),
            context(memory),
        )


@pytest.mark.asyncio
async def test_review_state_is_durable_terminal_and_admin_only(tmp_path: Path) -> None:
    database = tmp_path / "feedback.sqlite3"
    memory = DemoAgentMemory()
    user_context = context(memory)
    created = await service(database).process_feedback(
        feedback_request(
            rating="down",
            question="Show revenue",
            corrected_sql="SELECT SUM(amount) FROM invoices",
            enqueue_for_review=True,
        ),
        user_context,
    )

    restarted = service(database)
    admin_context = context(
        memory,
        user_id="reviewer",
        groups=("admin",),
    )
    queued = await restarted.list_review_queue(admin_context)
    assert [record.feedback_id for record in queued.records] == [created.feedback_id]
    with pytest.raises(PermissionError, match="admin"):
        await restarted.list_review_queue(user_context)

    reviewed = (
        await restarted.review_feedback(
            created.feedback_id,
            FeedbackReviewRequest(status="approved", reviewer_note="Verified"),
            admin_context,
        )
    ).record
    assert reviewed.review_status == "approved"
    assert reviewed.reviewer_id == "reviewer"
    assert reviewed.review_memory_patch_status == "applied"
    promoted = await memory.search_similar_usage(
        "Show revenue",
        context(memory, tenant="tenant-a", user_id="another-user"),
        similarity_threshold=0.0,
    )
    assert promoted[0].memory.metadata["review_status"] == "approved"
    assert promoted[0].memory.metadata["weight"] == 8.0

    with pytest.raises(FeedbackStateError, match="no longer pending"):
        await restarted.review_feedback(
            created.feedback_id,
            FeedbackReviewRequest(status="rejected"),
            admin_context,
        )


@pytest.mark.asyncio
async def test_rejected_feedback_is_removed_tenant_wide(tmp_path: Path) -> None:
    memory = DemoAgentMemory()
    submitter = context(memory, tenant="shared", user_id="alice")
    peer = context(memory, tenant="shared", user_id="bob")
    admin = context(memory, tenant="shared", user_id="admin", groups=("admin",))
    feedback = service(tmp_path / "feedback.sqlite3")
    created = await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="Show revenue",
            original_sql="SELECT wrong FROM revenue",
            corrected_sql="SELECT amount FROM revenue",
            enqueue_for_review=True,
        ),
        submitter,
    )
    assert await memory.search_similar_usage(
        "Show revenue", peer, similarity_threshold=0.0
    )

    rejected = (
        await feedback.review_feedback(
            created.feedback_id,
            FeedbackReviewRequest(status="rejected"),
            admin,
        )
    ).record

    assert rejected.review_memory_patch_status == "applied"
    assert (
        await memory.search_similar_usage(
            "Show revenue", peer, similarity_threshold=0.0
        )
        == []
    )


@pytest.mark.asyncio
async def test_review_cannot_overtake_initial_memory_publication(
    tmp_path: Path,
) -> None:
    memory = BlockingFeedbackMemory()
    submitter = context(memory, tenant="shared", user_id="alice")
    peer = context(memory, tenant="shared", user_id="bob")
    admin = context(memory, tenant="shared", user_id="admin", groups=("admin",))
    feedback = service(tmp_path / "feedback.sqlite3")
    submission = asyncio.create_task(
        feedback.process_feedback(
            feedback_request(
                rating="down",
                question="Show revenue",
                original_sql="SELECT wrong FROM revenue",
                corrected_sql="SELECT amount FROM revenue",
                enqueue_for_review=True,
            ),
            submitter,
        )
    )
    await asyncio.wait_for(memory.started.wait(), timeout=1.0)
    assert memory.feedback_id is not None
    assert (await feedback.list_review_queue(admin)).records == []

    with pytest.raises(FeedbackStateError, match="memory patch must be applied"):
        await feedback.review_feedback(
            memory.feedback_id,
            FeedbackReviewRequest(status="rejected"),
            admin,
        )

    memory.release.set()
    created = await asyncio.wait_for(submission, timeout=1.0)
    rejected = (
        await feedback.review_feedback(
            created.feedback_id,
            FeedbackReviewRequest(status="rejected"),
            admin,
        )
    ).record

    assert rejected.review_memory_patch_status == "applied"
    assert (
        await memory.search_similar_usage(
            "Show revenue", peer, similarity_threshold=0.0
        )
        == []
    )


@pytest.mark.asyncio
async def test_failed_review_memory_promotion_is_durable_and_retryable(
    tmp_path: Path,
) -> None:
    memory = FlakyReviewMemory()
    submitter = context(memory)
    admin = context(memory, user_id="admin", groups=("admin",))
    feedback = service(tmp_path / "feedback.sqlite3")
    created = await feedback.process_feedback(
        feedback_request(
            rating="down",
            question="Show revenue",
            corrected_sql="SELECT amount FROM revenue",
            enqueue_for_review=True,
        ),
        submitter,
    )

    with pytest.raises(FeedbackReviewMemoryPatchError) as exc_info:
        await feedback.review_feedback(
            created.feedback_id,
            FeedbackReviewRequest(status="approved"),
            admin,
        )
    assert "TOP_SECRET" not in str(exc_info.value)
    failed = feedback.store.get("tenant:tenant-a", created.feedback_id)
    assert failed is not None
    assert failed.review_status == "approved"
    assert failed.review_memory_patch_status == "failed"
    assert failed.review_memory_patch_attempts == 1

    retried = await feedback.retry_review_memory_patch(created.feedback_id, admin)
    assert retried.record.review_memory_patch_status == "applied"
    assert retried.record.review_memory_patch_attempts == 2


@pytest.mark.asyncio
async def test_training_export_contains_approved_records_only_and_manifest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "feedback.sqlite3"
    output = tmp_path / "approved.jsonl"
    memory = DemoAgentMemory()
    user_context = context(memory)
    feedback = service(database)
    approved = await feedback.process_feedback(
        feedback_request(rating="up", enqueue_for_review=True),
        user_context,
    )
    rejected = await feedback.process_feedback(
        feedback_request(rating="down", enqueue_for_review=True),
        user_context,
    )
    pending = await feedback.process_feedback(
        feedback_request(rating="up", enqueue_for_review=True),
        user_context,
    )
    admin_context = context(memory, user_id="admin", groups=("admin",))
    await feedback.review_feedback(
        approved.feedback_id,
        FeedbackReviewRequest(status="approved"),
        admin_context,
    )
    await feedback.review_feedback(
        rejected.feedback_id,
        FeedbackReviewRequest(status="rejected"),
        admin_context,
    )

    exported = await feedback.write_approved_export(admin_context, str(output))
    content = output.read_text(encoding="utf-8")

    assert exported.manifest.feedback_ids == [approved.feedback_id]
    assert pending.feedback_id not in content
    assert rejected.feedback_id not in content
    assert (
        exported.manifest.content_sha256
        == hashlib.sha256(content.encode("utf-8")).hexdigest()
    )
    manifest = json.loads(
        output.with_suffix(".jsonl.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["record_count"] == 1
    assert manifest["feedback_ids"] == [approved.feedback_id]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert (
        stat.S_IMODE(output.with_suffix(".jsonl.manifest.json").stat().st_mode) == 0o600
    )


@pytest.mark.asyncio
async def test_training_export_interruption_preserves_committed_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "approved.jsonl"
    manifest = output.with_suffix(".jsonl.manifest.json")
    memory = DemoAgentMemory()
    user_context = context(memory)
    admin_context = context(memory, user_id="admin", groups=("admin",))
    feedback = service(tmp_path / "feedback.sqlite3")

    first = await feedback.process_feedback(
        feedback_request(rating="up", enqueue_for_review=True),
        user_context,
    )
    await feedback.review_feedback(
        first.feedback_id,
        FeedbackReviewRequest(status="approved"),
        admin_context,
    )
    await feedback.write_approved_export(admin_context, str(output))
    committed_manifest = manifest.read_bytes()
    committed_export = load_training_export(manifest, output)

    second = await feedback.process_feedback(
        feedback_request(rating="up", enqueue_for_review=True),
        user_context,
    )
    await feedback.review_feedback(
        second.feedback_id,
        FeedbackReviewRequest(status="approved"),
        admin_context,
    )

    real_replace = os.replace

    def interrupt_manifest(source: object, destination: object) -> None:
        if Path(destination) == manifest:
            raise OSError("injected manifest publication interruption")
        real_replace(source, destination)

    monkeypatch.setattr("vanna.services.feedback.os.replace", interrupt_manifest)
    with pytest.raises(OSError, match="publication interruption"):
        await feedback.write_approved_export(admin_context, str(output))

    assert manifest.read_bytes() == committed_manifest
    assert load_training_export(manifest, output) == committed_export
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.asyncio
async def test_sqlite_feedback_lock_does_not_block_event_loop(tmp_path: Path) -> None:
    database = tmp_path / "feedback.sqlite3"
    memory = DemoAgentMemory()
    feedback = service(database)
    blocker = sqlite3.connect(database)
    blocker.execute("BEGIN IMMEDIATE")
    heartbeat_ticks = 0

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        for _ in range(8):
            await asyncio.sleep(0.01)
            heartbeat_ticks += 1

    submission = asyncio.create_task(
        feedback.process_feedback(feedback_request(rating="up"), context(memory))
    )
    pulse = asyncio.create_task(heartbeat())
    try:
        await asyncio.sleep(0.06)
        assert heartbeat_ticks >= 4
        assert not submission.done()
    finally:
        blocker.rollback()
        blocker.close()

    await asyncio.wait_for(submission, timeout=1.0)
    await pulse


@pytest.mark.asyncio
async def test_approved_export_rejects_unbounded_record_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = DemoAgentMemory()
    admin_context = context(memory, user_id="admin", groups=("admin",))
    feedback = service(tmp_path / "feedback.sqlite3")
    record = FeedbackRecord(
        feedback_id="fb-1",
        tenant_scope="tenant:tenant-a",
        user_id="user-a",
        rating="up",
        conversation_id="conv-1",
        request_id="req-1",
        created_at="2026-08-11T12:00:00Z",
        review_status="approved",
        reviewer_id="reviewer",
        reviewed_at="2026-08-11T12:01:00Z",
    )
    monkeypatch.setattr(
        feedback.store,
        "list_approved",
        lambda tenant_scope, *, limit: [record] * limit,
    )

    with pytest.raises(FeedbackExportLimitError, match="record limit"):
        await feedback.approved_export(admin_context)


def test_sqlite_store_rejects_non_durable_memory_mode() -> None:
    with pytest.raises(ValueError, match="durable"):
        SqliteFeedbackStore(":memory:")


def test_sqlite_store_uses_owner_only_directory_and_database_modes(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "feedback-private"
    database = private_directory / "feedback.sqlite3"

    SqliteFeedbackStore(str(database))

    assert stat.S_IMODE(private_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_feedback_input_rejects_unknown_or_malformed_reason_codes() -> None:
    with pytest.raises(ValidationError):
        feedback_request(rating="down", reason_codes=["raw SQL; DROP"])
    with pytest.raises(ValidationError):
        feedback_request(rating="up", attacker_controlled=True)  # type: ignore[call-arg]
