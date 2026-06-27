import pytest

from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory


def _ctx(mem):
    return ToolContext(
        user=User(id="u1", group_memberships=["user"]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=mem,
    )


@pytest.mark.asyncio
async def test_corrective_memory_outranks_plain_memory():
    mem = DemoAgentMemory()
    ctx = _ctx(mem)
    # an ordinary saved usage (default weight)
    await mem.save_tool_usage(
        question="show revenue by month",
        tool_name="run_sql",
        args={"sql": "SELECT bad"},
        context=ctx,
        success=True,
    )
    # a corrective, high-weight memory for a slightly less identical question
    await mem.save_tool_usage(
        question="show monthly revenue",
        tool_name="run_sql",
        args={"sql": "SELECT good"},
        context=ctx,
        success=True,
        metadata={"patch_type": "corrective", "weight": 5.0},
    )
    results = await mem.search_similar_usage(
        "show revenue by month", ctx, similarity_threshold=0.1
    )
    assert results, "expected at least one match"
    assert results[0].memory.args["sql"] == "SELECT good"
