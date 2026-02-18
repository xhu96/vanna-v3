"""Tests for immediate feedback memory patching."""

import pytest

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.services.feedback import FeedbackRequest, FeedbackService


@pytest.mark.asyncio
async def test_feedback_service_patches_negative_and_corrective_memory(tmp_path):
    memory = DemoAgentMemory()
    context = ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=memory,
    )
    service = FeedbackService(
        feedback_log_path=str(tmp_path / "feedback.jsonl"),
        review_queue_path=str(tmp_path / "review.jsonl"),
    )

    result = await service.process_feedback(
        FeedbackRequest(
            rating="down",
            question="What is monthly revenue?",
            original_sql="SELECT * FROM invoices",
            corrected_sql="SELECT DATE_TRUNC('month', created_at), SUM(amount) FROM invoices GROUP BY 1",
            reason_codes=["wrong_grain"],
            enqueue_for_review=True,
        ),
        context,
    )

    assert result.patched_memories == 2
    assert result.review_queued is True
    memories = await memory.get_recent_memories(context, limit=10)
    assert len(memories) >= 2
