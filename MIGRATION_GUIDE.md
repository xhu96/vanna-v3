# Migration Guide: Vanna 0.x to Vanna 2.0+

This guide will help you migrate from Vanna 0.x (legacy) to Vanna 2.0+, the new user-aware agent framework.

> **Note:** The legacy adapter (`LegacyVannaAdapter`) was removed in 3.0. This fork targets the v2.0+ agent architecture directly, so the only supported path is a full migration to the new architecture (below).

## Table of Contents
- [Overview of Changes](#overview-of-changes)
- [Migrating to the New Architecture](#migrating-to-the-new-architecture)
- [Key Architectural Differences](#key-architectural-differences)

---

## Overview of Changes

Vanna 2.0+ represents a fundamental architectural shift from a simple LLM wrapper to a full-fledged **user-aware agent framework**. Here are the major changes:

### What's New in 2.0+
- ✅ **User awareness** - Identity and permissions flow through every layer
- ✅ **Web component** - Pre-built UI with streaming responses
- ✅ **Tool registry** - Modular, extensible tool system
- ✅ **Rich UI components** - Tables, charts, status cards (not just text)
- ✅ **Streaming by default** - Progressive responses via SSE
- ✅ **Enterprise features** - Audit logs, rate limiting, observability
- ✅ **FastAPI/Flask servers** - Production-ready backends included

### What Changed from 0.x
- ❌ Direct method calls (`vn.ask()`) → Agent-based workflow
- ❌ Monolithic `VannaBase` class → Modular tool system
- ❌ No user context → User-aware at every layer
- ❌ Simple text responses → Rich streaming UI components

---

## Migrating to the New Architecture

**Best for:** New projects or teams ready for a complete rewrite.

#### Before (Vanna 0.x)

```python
from vanna import VannaBase
from vanna.openai_chat import OpenAI_Chat
from vanna.chromadb import ChromaDB_VectorStore

class MyVanna(ChromaDB_VectorStore, OpenAI_Chat):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        OpenAI_Chat.__init__(self, config=config)

vn = MyVanna(config={'model': 'gpt-4', 'api_key': 'your-key'})
vn.connect_to_postgres(...)

# Train
vn.train(ddl="CREATE TABLE customers ...")
vn.train(question="Top customers?", sql="SELECT ...")

# Ask
sql = vn.generate_sql("Who are the top customers?")
df = vn.run_sql(sql)
print(df)
```

#### After (Vanna 2.0+)

```python
from vanna import Agent, AgentConfig
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.core.registry import ToolRegistry
from vanna.core.user import UserResolver, User, RequestContext
from vanna.integrations.anthropic import AnthropicLlmService
from vanna.tools import RunSqlTool
from vanna.integrations.postgres import PostgresRunner

# 1. Define user resolution
class MyUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        # Extract from your auth system (JWT, cookies, etc.)
        token = request_context.get_header('Authorization')
        user_data = await self.validate_token(token)

        return User(
            id=user_data['id'],
            email=user_data['email'],
            permissions=user_data['permissions'],
            metadata={'role': user_data['role']}
        )

# 2. Set up tools
tools = ToolRegistry()
postgres_runner = PostgresRunner(
    host="localhost",
    dbname="mydb",
    user="user",
    password="password",
    port=5432
)
tools.register_local_tool(
    RunSqlTool(sql_runner=postgres_runner),
    access_groups=['user', 'admin']
)

# 3. Create agent
llm = AnthropicLlmService(model="claude-sonnet-4-5")
agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=MyUserResolver(),
    config=AgentConfig(stream_responses=True)
)

# 4. Create server
server = VannaFastAPIServer(agent)
app = server.create_app()

# Run with: uvicorn main:app --host 0.0.0.0 --port 8000
# Visit http://localhost:8000 for web UI
```

**Pros:**
- ✅ Full access to new features
- ✅ True user awareness
- ✅ Better security and permissions
- ✅ Production-ready architecture

**Cons:**
- ⚠️ Requires rewriting code
- ⚠️ Need to migrate training data approach
- ⚠️ Steeper learning curve

---

## Key Architectural Differences

| Feature | Vanna 0.x | Vanna 2.0+ |
|---------|-----------|------------|
| **User Context** | None | `User` object with permissions flows through entire system |
| **Interaction Model** | Direct method calls (`vn.ask()`) | Agent-based with streaming components |
| **Tools** | Monolithic methods | Modular `Tool` classes with schemas |
| **Responses** | Plain text/DataFrames | Rich UI components (tables, charts, code) |
| **Training** | `vn.train()` with vector DB | System prompts, context enrichers, RAG tools |
| **Database Connection** | `vn.connect_to_postgres()` | `SqlRunner` implementations as dependencies |
| **Web UI** | None (custom implementation) | Built-in web component + backend |
| **Streaming** | None | Server-Sent Events by default |
| **Permissions** | None | Group-based access control on tools |
| **Audit Logs** | None | Built-in audit logging system |

Good luck with your migration! 🚀
