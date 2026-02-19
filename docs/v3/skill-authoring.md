# Manual Skill Authoring Guide

This guide walks through creating a skill pack from scratch without the generator.

## Directory Structure

```
skill_packs/
└── my_domain_pack/
    ├── skill.yaml          # SkillSpec definition
    ├── eval_dataset.yaml   # Evaluation questions
    └── README.md           # Documentation
```

## Step 1: Define the SkillSpec

Create `skill.yaml`:

```yaml
name: my_domain_analytics
version: "1.0.0"
description: >
  Analytics skill for [your domain]. Enables questions about
  [key metrics] with [key constraints].

provenance:
  author: your-name

intents:
  patterns:
    - "(?i)\\b(metric1|metric2|keyword)\\b"
  embedding_hints:
    - "total metric1 by time_period"
    - "top N entities by metric2"
  tool_routing_hints:
    - "run_sql"

knowledge:
  synonyms:
    metric1:
      - alternative name 1
      - alternative name 2
  metric_definitions:
    metric1: "SUM(column) WHERE condition"
  semantic_mappings:
    business_concept: "table.column"

policies:
  required_filters:
    - "tenant_id = :tenant_id"
  column_redaction_rules:
    - "sensitive_column"
  sql_limits:
    read_only: true
    max_rows: 1000
    require_limit: true
    forbid_ddl_dml: true

rendering:
  currency: USD
  locale: en-US
  date_format: "YYYY-MM-DD"
  preferred_output_layout: table

eval_suite:
  pass_rate_threshold: 0.8
  min_score: 0.7
```

## Step 2: Write Evaluation Questions

Create `eval_dataset.yaml` with ≥15 questions:

```yaml
questions:
  - question: "What was the total [metric] last month?"
    constraints:
      - "uses SUM on correct column"
      - "applies date filter for last month"
    expected_tool: run_sql
    tags: [metric, time_filter]
```

### Writing Good Constraints

| ✅ Good                      | ❌ Bad                  |
| ---------------------------- | ----------------------- |
| "uses SUM on revenue column" | "generates correct SQL" |
| "applies LIMIT 10"           | "works properly"        |
| "filters to current quarter" | "is fast"               |
| "groups by product category" | "returns data"          |

Constraints should be **specific**, **verifiable**, and **SQL-aware**.

## Step 3: Validate with the Compiler

```python
import yaml
from vanna.skills.models import SkillSpec
from vanna.skills.compiler import SkillCompiler

with open("skill_packs/my_domain_pack/skill.yaml") as f:
    spec = SkillSpec(**yaml.safe_load(f))

compiler = SkillCompiler()
result = compiler.compile(spec)

if result.success:
    print("✅ Skill compiles successfully")
    if result.warnings:
        print(f"⚠️  Warnings: {result.warnings}")
else:
    print(f"❌ Errors: {result.errors}")
```

## Step 4: Register and Promote

```python
from vanna.skills.registry import SkillRegistry
from vanna.skills.stores import InMemorySkillRegistryStore

store = InMemorySkillRegistryStore()
registry = SkillRegistry(store)

# Register as draft
entry = await registry.register_skill(spec, actor="you", tenant_id="your_tenant")

# Promote through lifecycle
# See docs/v3/skill-lifecycle.md
```

## Sample Skill Packs

Two reference packs are included in the repository:

| Pack                             | Domain                  | Glossary           | Evals |
| -------------------------------- | ----------------------- | ------------------ | ----- |
| `skill_packs/retail_ops_basics/` | Retail / e-commerce     | 7 terms, 4 metrics | 15    |
| `skill_packs/uk_accounting/`     | UK accounting / finance | 8 terms, 4 metrics | 15    |

Use these as templates for your own domain-specific packs.

## Checklist Before Publishing

- [ ] Skill compiles with zero errors
- [ ] ≥15 eval questions with specific constraints
- [ ] Tenant isolation filter in `required_filters`
- [ ] Sensitive columns listed in `column_redaction_rules`
- [ ] `sql_limits.read_only` and `forbid_ddl_dml` are both `true`
- [ ] Glossary terms cover the key domain vocabulary
- [ ] Metric definitions use correct SQL
- [ ] README documents what the pack covers
