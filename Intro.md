# Vanna v3 — Project Introduction

## What does it do?

Vanna v3 is a **natural language → SQL → insights** agent framework. A user types a plain-English question ("What were our top 10 products last month?"), and the agent:

1. Routes through semantic planning
2. Generates and executes SQL against your database
3. Streams back typed UI components — tables, charts, summaries, lineage — in real time

It's a production-grade, enterprise-ready platform with an API server (FastAPI or Flask) that you deploy in front of your database.

---

## Functionalities

| Area | Features |
|---|---|
| **Core** | NL→SQL via LLM, streaming SSE events (v3 typed API), read-only SQL enforcement, 40+ database backends (Postgres, Snowflake, DuckDB, BigQuery, SQLite…) |
| **LLM** | 8+ providers (Claude, GPT-4, Gemini, Ollama, Mistral, Azure, OpenRouter, Bedrock) |
| **Agent Memory** | 10+ vector/semantic backends (ChromaDB, Pinecone, FAISS, Qdrant, Weaviate…) — learns from past queries |
| **Tools** | RunSQL, SemanticQuery, VisualizeData, FileSystem, Python, DbtDeploy, ExportData, FetchURL, StatisticalAnalysis |
| **Skills Fabric** | YAML-based declarative domain extensions with lifecycle (draft→tested→approved→default), approval workflows, intent routing |
| **Personalization** | Tenant + user profiles, glossary injection, session memory with PII redaction (Presidio), GDPR export/delete, double opt-in consent |
| **Security** | Tool RBAC (group-based), auth middleware hooks (JWT/OAuth), no `exec()` for charts (ChartSpec only), SQL DDL/DML blocking, multi-tenant RLS |
| **Observability** | Lineage + evidence panel, column-level lineage (SQLGlot), audit logging, confidence scoring |
| **Schema Sync** | Hash-based schema drift detection, auto memory patching on schema change |
| **Feedback Loop** | Thumbs up/down → immediate memory patches with weighted learning |
| **UI Components** | Rich streaming components: DataFrames, Charts (Vega-Lite/Plotly), Progress, Cards, Buttons, TaskList, Artifacts |
| **Deployment** | FastAPI or Flask server, CLI runner, 30+ example scripts, web components |

---

## Scores

### Data Engineering: 8/10

Very DE-heavy:
- DbtDeployTool: converts SQL → dbt model + tests + opens GitHub PR
- Column-level lineage extraction (SQLGlot)
- Schema drift detection + memory patching
- Flink, DataHub, Great Expectations, Cube.dev integrations
- 12+ SQL database connectors
- Schema catalog snapshots + diff engine
- SQL security enforcement (read-only, DDL blocking)
- Data export (CSV, Parquet…)

Misses a perfect 10 because it doesn't do pipeline orchestration, job scheduling, or transformations beyond the dbt integration.

### Agentic AI: 9/10

Very agentic by design:
- Full tool-use loop (LLM decides which tool to call with Pydantic-typed args)
- Persistent agent memory that improves over time
- Declarative skill fabric with intent routing
- Semantic-first planner
- LLM middlewares (caching, prompt engineering)
- Lifecycle hooks (rate limiting, quota, audit at every step)
- Multi-step reasoning with lineage + evidence
- Feedback → memory patching loop
- User-aware identity flows through every LLM/tool call
- Approval workflows for generated skills

Misses a perfect 10 because it's domain-specific (text→SQL), not a general-purpose reasoning agent, and lacks multi-agent coordination.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                  Client UI                       │
│  (<vanna-chat> web component or custom BYO UI)  │
└────────────────────┬─────────────────────────────┘
                     │ HTTP/SSE
                     ▼
┌──────────────────────────────────────────────────┐
│          API Layer (FastAPI / Flask)             │
│  POST /api/vanna/v3/chat/events                 │
│  POST /api/vanna/v3/feedback                    │
│  POST /api/vanna/v3/schema/sync                 │
│  + CORS, auth middleware, rate limit hooks       │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│              Agent Runtime                       │
│  ┌──────────────────────────────────────────┐   │
│  │ Agent (orchestrator)                     │   │
│  │  ├─ LlmHandler   (build/stream LLM)      │   │
│  │  ├─ ToolExecutor (run tools + hooks)     │   │
│  │  └─ EvidenceEmitter (lineage+confidence) │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  Planner · Memory · Lifecycle · Enhancer · Audit │
└──────────────────────────────────────────────────┘
              │
    ┌─────────┼──────────┬──────────┐
    ▼         ▼          ▼          ▼
┌───────┐ ┌──────┐ ┌────────┐ ┌──────────┐
│ Tools │ │ LLM  │ │ Memory │ │ Storage  │
│ 40+DB │ │  8+  │ │  10+   │ │ & Audit  │
└───────┘ └──────┘ └────────┘ └──────────┘
    │         │         │          │
    └─────────┴─────────┴──────────┘
                     │
┌──────────────────────────────────────────────────┐
│  External Services                               │
│  Postgres · Snowflake · BigQuery · SQLite · …   │
│  Claude · GPT-4 · Gemini · Ollama · …           │
│  ChromaDB · Pinecone · Qdrant · …               │
│  GitHub · dbt · Cube.dev · Great Expectations   │
└──────────────────────────────────────────────────┘
```

---

## TL;DR

A **secure, enterprise-grade, self-improving NL→SQL agent platform** — a data tool at its core, built with full agentic AI infrastructure.