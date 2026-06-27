import json
import pytest

from vanna.integrations.mock.scripted_llm import ScriptedLlmService


@pytest.mark.asyncio
async def test_scripted_llm_returns_mapped_answer():
    llm = ScriptedLlmService(
        responses={"total sales by region": "SELECT region, SUM(amount) FROM sales GROUP BY region"},
        default="SELECT 1",
    )
    from vanna.core import LlmRequest, LlmMessage
    from vanna.core.user import User

    req = LlmRequest(
        user=User(id="u1", group_memberships=["user"]),
        messages=[LlmMessage(role="user", content="show me total sales by region")],
    )
    resp = await llm.send_request(req)
    assert "SELECT" in resp.content and "region" in resp.content


def test_offline_eval_runner_importable():
    # the pipeline module must import without side effects
    import src.evals.pipelines.run_offline_eval as m  # noqa: F401
    assert hasattr(m, "run_offline_eval")
