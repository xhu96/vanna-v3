# Contributing to Vanna

Thank you for your interest in contributing to Vanna! This guide will help you get started with contributing to the Vanna 2.0+ codebase.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Architecture Overview](#architecture-overview)
- [Adding New Features](#adding-new-features)

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Git
- A GitHub account

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:

   ```bash
   git clone https://github.com/YOUR_USERNAME/vanna.git
   cd vanna
   ```

3. Add the upstream repository:
   ```bash
   git remote add upstream https://github.com/vanna-ai/vanna.git
   ```

---

## Development Setup

### 1. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
# Install the package in editable mode with all extras
pip install -e ".[all]"

# Install development tools
pip install tox ruff mypy pytest pytest-asyncio
```

### 3. Verify Installation

```bash
# Run unit tests
tox -e py311-unit

# Run type checking
tox -e mypy

# Run format checking
tox -e ruff
```

---

## Code Standards

### Formatting

We use [ruff](https://github.com/astral-sh/ruff) for code formatting and linting.

```bash
# Check formatting
ruff format --check src/vanna/ tests/

# Apply formatting
ruff format src/vanna/ tests/

# Run linting
ruff check src/vanna/ tests/
```

### Type Checking

We use mypy with strict mode for type checking:

```bash
tox -e mypy
```

All new code should include type hints.

### Code Style Guidelines

- Follow PEP 8 style guidelines
- Use descriptive variable and function names
- Add docstrings to all public functions and classes
- Keep functions focused and single-purpose
- Avoid circular imports by using `TYPE_CHECKING`

**Example:**

```python
"""Module docstring explaining the purpose."""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from vanna.core.user import User

class MyClass:
    """Class docstring explaining what this class does."""

    async def my_method(self, user: "User", count: int = 10) -> Optional[str]:
        """Method docstring explaining parameters and return value.

        Args:
            user: The user making the request
            count: Maximum number of items to return

        Returns:
            Result string if found, None otherwise
        """
        pass
```

---

## Testing

### Test Organization

Tests are organized in the `tests/` directory by category:

**Core & Security:**

- `test_tool_permissions.py` - Tool access control and group-based permissions
- `test_sql_security.py` - Read-only SQL enforcement and injection prevention
- `test_legacy_chart_security.py` - Legacy chart execution security defaults

**Agent & Workflow:**

- `test_agents.py` - End-to-end agent tests (multi-LLM)
- `test_workflow.py` - Agent workflow and admin command tests
- `test_memory_tools.py` - Memory tool detailed results and admin/user views
- `test_llm_context_enhancer.py` - LLM context enhancement tests

**v3 Features:**

- `test_v3_stream_events.py` - Typed streaming event contracts
- `test_chart_spec_validation.py` - Declarative ChartSpec validation
- `test_visualization_tool.py` - Visualization tool output tests
- `test_schema_diff.py` - Schema drift detection and memory patching
- `test_semantic_planner.py` - Semantic-first planner routing
- `test_lineage_capture.py` - Lineage and evidence collection
- `test_feedback_memory_patching.py` - Feedback loop memory patching

**Integration (LLM):**

- `test_gemini_integration.py` - Gemini LLM service unit tests
- `test_gemini_e2e.py` - Gemini full pipeline e2e tests (Chinook DB)
- `test_duckdb_public_api.py` - DuckDB + free public data tests

**Integration (Memory & Database):**

- `test_agent_memory.py` - Agent memory backend tests
- `test_agent_memory_sanity.py` - Memory implementation sanity checks
- `test_database_sanity.py` - Database runner sanity checks
- `test_legacy_adapter.py` - Legacy v2 compatibility tests

**Personalization:**

- `test_personalization_models.py` - User/tenant profile model validation
- `test_profile_service.py` - Profile/glossary CRUD, RBAC, consent
- `test_pii_redaction.py` - PII detection and storage policy
- `test_preference_resolver.py` - Preference injection into system prompt

**Skill Fabric:**

- `test_skill_models.py` - SkillSpec, CompiledSkill model validation
- `test_skill_compiler.py` - Deterministic compiler validation rules
- `test_skill_registry.py` - Skill lifecycle, promotion, rollback, RBAC
- `test_skill_router.py` - Skill matching, context merging
- `test_skill_generator.py` - Template/LLM generation, safety guarantees
- `test_e2e_personalization_skills.py` - Full pipeline integration test

### Running Tests

```bash
# Run all unit tests (no external dependencies)
tox -e py311-unit

# Run v3 feature tests
tox -e py311-v3-unit

# Run specific test file
pytest tests/test_tool_permissions.py -v

# Run tests with a specific marker
pytest tests/ -v -m gemini
pytest tests/ -v -m anthropic

# Run Gemini integration tests
tox -e py311-gemini

# Run personalization tests
tox -e py311-personalization

# Run skill fabric tests
tox -e py311-skills

# Run legacy adapter tests
tox -e py311-legacy
```

### Writing Tests

1. **Unit tests** should not require external dependencies (databases, APIs, etc.)
2. Use **pytest markers** for tests that require external services:

   ```python
   @pytest.mark.gemini       # Requires GEMINI_API_KEY or GOOGLE_API_KEY
   @pytest.mark.anthropic    # Requires ANTHROPIC_API_KEY
   @pytest.mark.openai       # Requires OPENAI_API_KEY
   @pytest.mark.asyncio
   async def test_with_llm():
       # Test code here
       pass
   ```

3. **Mock external dependencies** in unit tests:

   ```python
   class MockLlmService(LlmService):
       async def send_request(self, request):
           # Mock implementation
           pass
   ```

4. **Test both success and failure cases**
5. **Use descriptive test names** that explain what is being tested

### Test Coverage

When adding new features, ensure:

- Core functionality is covered by unit tests
- Integration points are tested
- Error handling is validated
- Edge cases are considered

---

## Pull Request Process

### 1. Create a Feature Branch

```bash
git checkout -b feature/my-new-feature
# or
git checkout -b fix/bug-description
```

### 2. Make Your Changes

- Write your code following the code standards
- Add tests for your changes
- Update documentation as needed

### 3. Run All Checks

```bash
# Format code
ruff format src/vanna/ tests/

# Run linting
ruff check src/vanna/ tests/

# Run type checking
tox -e mypy

# Run tests
tox -e py311-unit
```

### 4. Commit Your Changes

Use clear, descriptive commit messages:

```bash
git add .
git commit -m "feat: add new LLM context enhancer for RAG

- Implements TextMemoryEnhancer class
- Adds tests for memory retrieval
- Updates documentation"
```

**Commit message format:**

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Adding or updating tests
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

### 5. Push and Create PR

```bash
git push origin feature/my-new-feature
```

Then create a pull request on GitHub with:

- Clear title describing the change
- Description of what was changed and why
- Link to any related issues
- Screenshots or examples if applicable

### 6. Code Review

- Address review feedback promptly
- Keep discussions focused and professional
- Be open to suggestions and alternative approaches

---

## Architecture Overview

### Core Components

Vanna 2.0+ is built around several key abstractions:

#### 1. **Agent** (`vanna.core.agent`)

The main orchestrator that coordinates tools, memory, and LLM interactions.

#### 2. **Tools** (`vanna.tools`, `vanna.core.tool`)

Modular capabilities that the agent can use. Each tool:

- Has a schema defining its inputs
- Implements an `execute()` method
- Declares access control via `access_groups`

#### 3. **Tool Registry** (`vanna.core.registry`)

Manages tool registration and access control.

#### 4. **Agent Memory** (`vanna.capabilities.agent_memory`)

Stores and retrieves tool usage patterns and documentation.

#### 5. **LLM Services** (`vanna.core.llm`)

Abstract interface for different LLM providers (Google Gemini, Anthropic, OpenAI, Ollama, Azure OpenAI, etc.).

#### 6. **SQL Runners** (`vanna.capabilities.sql_runner`)

Abstract interface for executing SQL against different databases.

#### 7. **Components** (`vanna.components`)

Rich UI components for rendering results (tables, charts, status cards, etc.).

### Data Flow

```
User Request → Agent → LLM Service → Tool Selection → Tool Execution → Response Components
                ↓                                           ↓
          Agent Memory                              SQL Runner / Other Capabilities
```

---

## Adding New Features

### Adding a New Tool

1. **Create the tool class** in `src/vanna/tools/`:

```python
from vanna.core.tool import Tool, ToolContext, ToolResult
from pydantic import BaseModel, Field

class MyToolArgs(BaseModel):
    """Arguments for my tool."""
    query: str = Field(description="The query to process")

class MyTool(Tool[MyToolArgs]):
    """Tool that does something useful."""

    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful with a query"

    def get_args_schema(self) -> type[MyToolArgs]:
        return MyToolArgs

    async def execute(
        self,
        context: ToolContext,
        args: MyToolArgs
    ) -> ToolResult:
        # Implement your tool logic
        result = f"Processed: {args.query}"

        return ToolResult(
            success=True,
            result_for_llm=result,
            ui_component=None
        )
```

2. **Add tests** in `tests/test_my_tool.py`

3. **Register the tool** in examples or documentation

### Adding a New Database Integration

1. **Implement SqlRunner** in `src/vanna/integrations/mydb/`:

```python
from vanna.capabilities.sql_runner import SqlRunner, RunSqlToolArgs
from vanna.core.tool import ToolContext
import pandas as pd

class MyDbRunner(SqlRunner):
    """SQL runner for MyDB database."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        # Initialize your DB connection

    async def run_sql(
        self,
        args: RunSqlToolArgs,
        context: ToolContext
    ) -> pd.DataFrame:
        # Execute SQL and return DataFrame
        pass
```

2. **Add sanity tests** in `tests/test_database_sanity.py`

3. **Add tox target** in `tox.ini`

4. **Update documentation**

### Adding a New LLM Integration

1. **Implement LlmService** in `src/vanna/integrations/myllm/`:

```python
from vanna.core.llm.base import LlmService
from vanna.core.llm.models import LlmRequest, LlmResponse, LlmStreamChunk
from typing import AsyncGenerator

class MyLlmService(LlmService):
    """LLM service for MyLLM provider."""

    def __init__(self, api_key: str, model: str = "default"):
        self.api_key = api_key
        self.model = model

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        # Implement API call
        pass

    async def stream_request(
        self,
        request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        # Implement streaming API call
        yield LlmStreamChunk(...)

    async def validate_tools(self, tools) -> list[str]:
        # Validate tool schemas
        return []
```

2. **Add tests** with the `@pytest.mark.myllm` marker

3. **Add tox target** for integration tests

### Adding a New Agent Memory Backend

1. **Implement AgentMemory** in `src/vanna/integrations/mystore/`:

```python
from vanna.capabilities.agent_memory import (
    AgentMemory,
    ToolMemory,
    ToolMemorySearchResult,
    TextMemory,
    TextMemorySearchResult
)
from vanna.core.tool import ToolContext

class MyStoreMemory(AgentMemory):
    """Agent memory using MyStore vector database."""

    async def save_tool_usage(self, question, tool_name, args, context, success=True, metadata=None):
        # Implement storage
        pass

    async def search_similar_usage(self, question, context, *, limit=10, similarity_threshold=0.7, tool_name_filter=None):
        # Implement search
        pass

    # Implement other AgentMemory methods...
```

2. **Add tests** in `tests/test_agent_memory.py`

3. **Add to extras** in `pyproject.toml`

---

## Legacy Compatibility

If you're working on legacy VannaBase compatibility:

- The `LegacyVannaAdapter` bridges legacy code with Vanna 2.0+
- Add tests to `tests/test_legacy_adapter.py`
- See `src/vanna/legacy/adapter.py` for examples

---

## Getting Help

- **Documentation**: https://vanna.ai/docs/
- **GitHub Issues**: https://github.com/vanna-ai/vanna/issues
- **Discussions**: https://github.com/vanna-ai/vanna/discussions

---

## License

By contributing to Vanna, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to Vanna! 🎉
