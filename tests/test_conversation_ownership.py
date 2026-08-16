"""Regression tests for fail-closed conversation ownership."""

from __future__ import annotations

import asyncio
import os
import stat
import threading
from pathlib import Path
from typing import AsyncGenerator, Callable

import pytest

from vanna.core.agent import Agent
from vanna.core.llm import LlmRequest, LlmStreamChunk
from vanna.core.registry import ToolRegistry
from vanna.core.storage import (
    Conversation,
    ConversationAccessDeniedError,
    ConversationAlreadyExistsError,
    ConversationCorruptError,
    InvalidConversationIdError,
    Message,
)
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local import (
    FileSystemConversationStore,
    MemoryConversationStore,
)
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock.scripted_llm import ScriptedLlmService


StoreFactory = Callable[[], MemoryConversationStore | FileSystemConversationStore]


class HeaderUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id=request_context.headers["x-user-id"])


class CountingScriptedLlmService(ScriptedLlmService):
    def __init__(self) -> None:
        super().__init__({}, default="complete")
        self.stream_call_count = 0

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        self.stream_call_count += 1
        async for chunk in super().stream_request(request):
            yield chunk


@pytest.fixture(params=["memory", "filesystem"])
def store_factory(request: pytest.FixtureRequest, tmp_path: Path) -> StoreFactory:
    if request.param == "memory":
        return MemoryConversationStore
    return lambda: FileSystemConversationStore(str(tmp_path / "conversations"))


@pytest.mark.asyncio
async def test_foreign_conversation_is_denied_not_reported_missing(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()
    alice = User(id="alice")
    bob = User(id="bob")
    await store.create_conversation("shared-id", alice, "alice secret")

    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.get_conversation("shared-id", bob)

    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.create_conversation("shared-id", bob, "replacement")

    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.update_conversation_for_user(
            Conversation(id="shared-id", user=alice, messages=[]), bob
        )

    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.delete_conversation("shared-id", bob)

    assert await store.list_conversations(bob) == []

    original = await store.get_conversation("shared-id", alice)
    assert original is not None
    assert original.user.id == "alice"
    assert [message.content for message in original.messages] == ["alice secret"]


@pytest.mark.asyncio
async def test_same_subject_in_different_tenant_is_denied(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()
    tenant_a = User(id="shared-subject", metadata={"tenant_id": "tenant-a"})
    tenant_b = User(id="shared-subject", metadata={"tenant_id": "tenant-b"})
    await store.create_conversation("tenant-qualified-id", tenant_a, "tenant-a secret")

    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.get_conversation("tenant-qualified-id", tenant_b)
    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.update_conversation_for_user(
            Conversation(
                id="tenant-qualified-id",
                user=tenant_a,
                messages=[],
            ),
            tenant_b,
        )
    with pytest.raises(ConversationAccessDeniedError, match="access denied"):
        await store.delete_conversation("tenant-qualified-id", tenant_b)

    assert await store.list_conversations(tenant_b) == []
    loaded = await store.get_conversation("tenant-qualified-id", tenant_a)
    assert loaded is not None
    assert [message.content for message in loaded.messages] == ["tenant-a secret"]


@pytest.mark.asyncio
async def test_same_owner_cannot_accidentally_recreate_identifier(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()
    alice = User(id="alice")
    await store.create_conversation("stable-id", alice, "first")

    with pytest.raises(ConversationAlreadyExistsError, match="already exists"):
        await store.create_conversation("stable-id", alice, "second")


@pytest.mark.asyncio
async def test_memory_store_does_not_expose_mutable_owner_alias() -> None:
    store = MemoryConversationStore()
    alice = User(id="alice")
    created = await store.create_conversation("copy-id", alice, "private")
    created.user = User(id="bob")

    loaded = await store.get_conversation("copy-id", alice)
    assert loaded is not None
    loaded.user = User(id="bob")

    persisted = await store.get_conversation("copy-id", alice)
    assert persisted is not None
    assert persisted.user.id == "alice"


@pytest.mark.asyncio
async def test_memory_store_serializes_threaded_conflicting_claims() -> None:
    store = MemoryConversationStore()
    barrier = threading.Barrier(2)

    def claim(user_id: str) -> Conversation:
        barrier.wait(timeout=5)
        return asyncio.run(
            store.create_conversation("thread-id", User(id=user_id), user_id)
        )

    results = await asyncio.gather(
        asyncio.to_thread(claim, "alice"),
        asyncio.to_thread(claim, "bob"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, Conversation) for result in results) == 1
    assert (
        sum(isinstance(result, ConversationAccessDeniedError) for result in results)
        == 1
    )


@pytest.mark.asyncio
async def test_concurrent_conflicting_create_has_one_owner(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()
    alice = User(id="alice")
    bob = User(id="bob")

    results = await asyncio.gather(
        store.create_conversation("race-id", alice, "alice"),
        store.create_conversation("race-id", bob, "bob"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, Conversation) for result in results) == 1
    assert (
        sum(isinstance(result, ConversationAccessDeniedError) for result in results)
        == 1
    )

    owner = alice if isinstance(results[0], Conversation) else bob
    conversation = await store.get_conversation("race-id", owner)
    assert conversation is not None
    assert conversation.user.id == owner.id


@pytest.mark.asyncio
async def test_agent_atomically_claims_conversation_before_processing(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()
    llm_service = CountingScriptedLlmService()
    agent = Agent(
        llm_service=llm_service,
        tool_registry=ToolRegistry(),
        user_resolver=HeaderUserResolver(),
        agent_memory=DemoAgentMemory(),
        conversation_store=store,
    )

    async def send_as(user_id: str) -> list[object]:
        return [
            component
            async for component in agent.send_message(
                RequestContext(headers={"x-user-id": user_id}),
                f"message from {user_id}",
                conversation_id="agent-race-id",
            )
        ]

    results = await asyncio.gather(send_as("alice"), send_as("bob"))
    assert all(results)
    assert llm_service.call_count + llm_service.stream_call_count == 1

    owners = []
    for user_id in ("alice", "bob"):
        try:
            conversation = await store.get_conversation(
                "agent-race-id", User(id=user_id)
            )
        except ConversationAccessDeniedError:
            continue
        if conversation is not None:
            owners.append(conversation.user.id)
    assert owners in (["alice"], ["bob"])


@pytest.mark.asyncio
async def test_claim_precedes_hooks_and_starter_workflow(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()

    class ClaimCheckingHook:
        async def before_message(self, user: User, message: str) -> None:
            del message
            assert await store.get_conversation("hook-claim", user) is not None

        async def after_message(self, result: object) -> None:
            del result

    class ClaimCheckingWorkflow:
        async def get_starter_ui(
            self, agent: Agent, user: User, conversation: Conversation
        ) -> list[object]:
            del agent
            assert conversation.id == "starter-claim"
            assert await store.get_conversation("starter-claim", user) is not None
            return []

    hook_agent = Agent(
        llm_service=ScriptedLlmService({}, default="complete"),
        tool_registry=ToolRegistry(),
        user_resolver=HeaderUserResolver(),
        agent_memory=DemoAgentMemory(),
        conversation_store=store,
        lifecycle_hooks=[ClaimCheckingHook()],  # type: ignore[list-item]
    )
    _ = [
        component
        async for component in hook_agent.send_message(
            RequestContext(headers={"x-user-id": "alice"}),
            "hello",
            conversation_id="hook-claim",
        )
    ]

    starter_agent = Agent(
        llm_service=ScriptedLlmService({}, default="not reached"),
        tool_registry=ToolRegistry(),
        user_resolver=HeaderUserResolver(),
        agent_memory=DemoAgentMemory(),
        conversation_store=store,
        workflow_handler=ClaimCheckingWorkflow(),  # type: ignore[arg-type]
    )
    assert [
        component
        async for component in starter_agent.send_message(
            RequestContext(headers={"x-user-id": "alice"}),
            "",
            conversation_id="starter-claim",
        )
    ] == []


@pytest.mark.asyncio
async def test_same_owner_concurrent_snapshots_append_without_message_loss(
    store_factory: StoreFactory,
) -> None:
    store = store_factory()
    alice = User(id="alice")
    first, _ = await store.claim_conversation("same-owner", alice)
    second, _ = await store.claim_conversation("same-owner", alice)
    first.add_message(Message(role="user", content="request-a"))
    second.add_message(Message(role="user", content="request-b"))

    await asyncio.gather(
        store.update_conversation_for_user(first, alice),
        store.update_conversation_for_user(second, alice),
    )

    persisted = await store.get_conversation("same-owner", alice)
    assert persisted is not None
    assert {message.content for message in persisted.messages} == {
        "request-a",
        "request-b",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "metadata"),
    [
        ("replace this conversation", {}),
        ("", {"starter_ui_request": True}),
    ],
)
async def test_agent_request_cannot_take_over_foreign_conversation(
    store_factory: StoreFactory, message: str, metadata: dict[str, bool]
) -> None:
    store = store_factory()
    alice = User(id="alice")
    await store.create_conversation("agent-shared-id", alice, "private history")
    agent = Agent(
        llm_service=ScriptedLlmService({}, default="not reached"),
        tool_registry=ToolRegistry(),
        user_resolver=HeaderUserResolver(),
        agent_memory=DemoAgentMemory(),
        conversation_store=store,
    )

    components = [
        component
        async for component in agent.send_message(
            RequestContext(headers={"x-user-id": "bob"}, metadata=metadata),
            message,
            conversation_id="agent-shared-id",
        )
    ]

    assert components, "public API should return a redacted error response"
    original = await store.get_conversation("agent-shared-id", alice)
    assert original is not None
    assert original.user.id == "alice"
    assert [message.content for message in original.messages] == ["private history"]


@pytest.mark.asyncio
async def test_filesystem_ids_and_corrupt_metadata_fail_closed(tmp_path: Path) -> None:
    store = FileSystemConversationStore(str(tmp_path / "conversations"))
    alice = User(id="alice")

    with pytest.raises(InvalidConversationIdError):
        await store.create_conversation("../escape", alice, "blocked")
    with pytest.raises(InvalidConversationIdError):
        await store.create_conversation(str(tmp_path / "absolute"), alice, "blocked")

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "conversations" / "linked-id").symlink_to(outside)
    with pytest.raises(InvalidConversationIdError):
        await store.create_conversation("linked-id", alice, "blocked")

    corrupt_dir = tmp_path / "conversations" / "corrupt-id"
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "metadata.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ConversationCorruptError):
        await store.get_conversation("corrupt-id", alice)

    nested_store = FileSystemConversationStore(str(tmp_path / "nested-links"))
    await nested_store.create_conversation("nested-id", alice, "private")
    messages_dir = tmp_path / "nested-links" / "nested-id" / "messages"
    for message_path in messages_dir.iterdir():
        message_path.unlink()
    messages_dir.rmdir()
    messages_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConversationCorruptError):
        await nested_store.get_conversation("nested-id", alice)

    external_base = tmp_path / "external-base"
    external_base.mkdir()
    linked_base = tmp_path / "linked-base"
    linked_base.symlink_to(external_base, target_is_directory=True)
    with pytest.raises(InvalidConversationIdError):
        FileSystemConversationStore(str(linked_base))

    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(external_parent, target_is_directory=True)
    with pytest.raises(InvalidConversationIdError):
        FileSystemConversationStore(str(linked_parent / "conversations"))


@pytest.mark.asyncio
async def test_filesystem_update_cannot_reclaim_concurrently_reassigned_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_dir = tmp_path / "locked-conversations"
    alice_store = FileSystemConversationStore(str(base_dir))
    bob_store = FileSystemConversationStore(str(base_dir))
    alice = User(id="alice")
    bob = User(id="bob")
    await alice_store.create_conversation("locked-id", alice, "alice history")
    alice_conversation = await alice_store.get_conversation("locked-id", alice)
    assert alice_conversation is not None

    save_entered = threading.Event()
    allow_save = threading.Event()
    original_save = alice_store._save_metadata

    def paused_save(conversation: Conversation) -> None:
        save_entered.set()
        assert allow_save.wait(timeout=5)
        original_save(conversation)

    monkeypatch.setattr(alice_store, "_save_metadata", paused_save)

    async def update_alice() -> None:
        await asyncio.to_thread(
            lambda: asyncio.run(
                alice_store.update_conversation_for_user(alice_conversation, alice)
            )
        )

    async def reassign_to_bob() -> None:
        def reassign() -> None:
            assert asyncio.run(bob_store.delete_conversation("locked-id", alice))
            asyncio.run(bob_store.create_conversation("locked-id", bob, "bob history"))

        await asyncio.to_thread(reassign)

    alice_task = asyncio.create_task(update_alice())
    assert await asyncio.to_thread(save_entered.wait, 5)
    bob_task = asyncio.create_task(reassign_to_bob())
    try:
        await asyncio.sleep(0.1)
        assert not bob_task.done(), "reassignment must wait for the ownership lock"
    finally:
        allow_save.set()
    await asyncio.gather(alice_task, bob_task)

    final = await bob_store.get_conversation("locked-id", bob)
    assert final is not None
    assert final.user.id == "bob"
    assert [message.content for message in final.messages] == ["bob history"]


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name == "nt", reason="POSIX mode bits are not portable to Windows"
)
async def test_filesystem_store_enforces_owner_only_modes(tmp_path: Path) -> None:
    base_dir = tmp_path / "private-conversations"
    previous_umask = os.umask(0o022)
    try:
        store = FileSystemConversationStore(str(base_dir))
        await store.create_conversation("private-id", User(id="alice"), "secret")
    finally:
        os.umask(previous_umask)

    conversation_dir = base_dir / "private-id"
    messages_dir = conversation_dir / "messages"
    directory_paths = [base_dir, base_dir / ".locks", conversation_dir, messages_dir]
    file_paths = [
        conversation_dir / "metadata.json",
        base_dir / ".locks" / "private-id.lock",
        *messages_dir.glob("*.json"),
    ]

    assert file_paths[-1].is_file()
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in directory_paths)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in file_paths)
