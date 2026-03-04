"""OpenRouter example using OpenRouterLlmService.

OpenRouter is OpenAI-compatible. This demo loads environment from .env (via
python-dotenv if installed), then sends a simple message through an Agent.

Run:
  PYTHONPATH=. python vanna/examples/openrouter_quickstart.py

Required env:
  - OPENROUTER_API_KEY

Recommended env:
  - OPENROUTER_MODEL (e.g. "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet")
  - OPENROUTER_HTTP_REFERER, OPENROUTER_APP_TITLE
"""

import asyncio
import importlib.util
import os
import sys


def ensure_env() -> None:
    if importlib.util.find_spec("dotenv") is not None:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)
    else:
        print(
            "[warn] python-dotenv not installed; skipping .env load. Install with: pip install python-dotenv"
        )

    if not os.getenv("OPENROUTER_API_KEY"):
        print(
            "[error] OPENROUTER_API_KEY is not set. Add it to your environment or .env file."
        )
        sys.exit(1)


async def main() -> None:
    ensure_env()

    try:
        from vanna.integrations.openrouter import OpenRouterLlmService
    except ImportError:
        print(
            "[error] openrouter extra not installed. Install with: pip install -e .[openrouter]"
        )
        raise

    from vanna import AgentConfig, Agent, User
    from vanna.core.registry import ToolRegistry
    from vanna.tools import ListFilesTool

    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    print(f"Using OpenRouter model: {model}")

    llm = OpenRouterLlmService(model=model)

    tool_registry = ToolRegistry()
    tool_registry.register(ListFilesTool())

    agent = Agent(
        llm_service=llm,
        config=AgentConfig(stream_responses=False, temperature=1.0),
        tool_registry=tool_registry,
    )

    user = User(id="demo-user", username="demo")
    conversation_id = "openrouter-demo"

    print("Sending: 'List the files in the current directory'\n")
    async for component in agent.send_message(
        user=user,
        message="List the files in the current directory",
        conversation_id=conversation_id,
    ):
        if hasattr(component, "content") and component.content:
            print("Assistant:", component.content)


if __name__ == "__main__":
    asyncio.run(main())
