"""Tests for conversation-scoped lineage isolation."""

from types import SimpleNamespace

import pytest

from app.base.chat_handler import ChatHandler


class FakeAgent:
    """Minimal agent stub for ChatHandler construction."""

    pass


@pytest.fixture
def handler() -> ChatHandler:
    return ChatHandler(agent=FakeAgent())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Conversation-scoped storage
# ---------------------------------------------------------------------------


class TestLineageIsolation:
    def test_lineage_stored_per_conversation(self, handler: ChatHandler) -> None:
        """Two conversations should store separate lineage evidence."""
        rc_a = SimpleNamespace(
            data={"evidence": {"sql": "SELECT 1"}},
            content="## Lineage A",
        )
        rc_b = SimpleNamespace(
            data={"evidence": {"sql": "SELECT 2"}},
            content="## Lineage B",
        )

        handler._capture_lineage("conv_a", rc_a)
        handler._capture_lineage("conv_b", rc_b)

        assert handler.get_lineage("conv_a") == {"sql": "SELECT 1"}
        assert handler.get_lineage("conv_b") == {"sql": "SELECT 2"}
        assert handler.get_lineage_markdown("conv_a") == "## Lineage A"
        assert handler.get_lineage_markdown("conv_b") == "## Lineage B"

    def test_lineage_missing_conversation_returns_none(
        self, handler: ChatHandler
    ) -> None:
        """Querying for an unknown conversation returns None."""
        assert handler.get_lineage("unknown_conv") is None
        assert handler.get_lineage_markdown("unknown_conv") is None

    def test_lineage_updates_same_conversation(self, handler: ChatHandler) -> None:
        """Subsequent captures for the same conversation overwrite the old data."""
        rc_old = SimpleNamespace(data={"evidence": "old"}, content="old")
        rc_new = SimpleNamespace(data={"evidence": "new"}, content="new")

        handler._capture_lineage("conv1", rc_old)
        handler._capture_lineage("conv1", rc_new)

        assert handler.get_lineage("conv1") == "new"
        assert handler.get_lineage_markdown("conv1") == "new"


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


class TestLineageLruEviction:
    def test_lru_eviction(self, handler: ChatHandler) -> None:
        """When capacity is exceeded, the oldest entries are evicted."""
        max_entries = handler._max_lineage_entries
        for i in range(max_entries + 1):
            rc = SimpleNamespace(data={"evidence": i}, content=f"md_{i}")
            handler._capture_lineage(f"conv_{i}", rc)

        # First entry should be evicted
        assert handler.get_lineage("conv_0") is None
        # Last entry should still be present
        assert handler.get_lineage(f"conv_{max_entries}") == max_entries

    def test_lru_access_refreshes_entry(self, handler: ChatHandler) -> None:
        """Re-capturing for a conversation moves it to the end (not evicted)."""
        # Fill to capacity
        max_entries = handler._max_lineage_entries
        for i in range(max_entries):
            rc = SimpleNamespace(data={"evidence": i}, content=f"md_{i}")
            handler._capture_lineage(f"conv_{i}", rc)

        # Re-capture for conv_0 (refreshes it)
        rc_refresh = SimpleNamespace(data={"evidence": "refreshed"}, content="refreshed")
        handler._capture_lineage("conv_0", rc_refresh)

        # Add one more — conv_1 should be evicted (it's now the oldest)
        rc_new = SimpleNamespace(data={"evidence": "new"}, content="new")
        handler._capture_lineage("conv_new", rc_new)

        assert handler.get_lineage("conv_1") is None  # Evicted
        assert handler.get_lineage("conv_0") == "refreshed"  # Still present
