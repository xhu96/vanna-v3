# Skill Generation Guide

The `SkillGenerator` creates proposed SkillSpecs from a natural language description and a database schema. Generated skills are **proposal-only** — they are always created as `draft` and cannot be auto-promoted.

## How Generation Works

```
Description + Schema + Glossary
         ↓
   SkillGenerator
         ↓
  ┌──────────────────┐
  │ SkillSpec (draft) │ ← forced draft environment
  │ Eval Dataset      │ ← ≥10 questions
  │ Risk Checklist    │ ← security assessment
  │ Compilation Check │ ← auto-validated
  └──────────────────┘
```

## Using the Generator

### Template Mode (No LLM)

```python
from vanna.skills.generator import SkillGenerator

gen = SkillGenerator()
output = await gen.generate(
    schema_catalog={
        "tables": {
            "orders": {"columns": ["id", "customer_id", "total", "status", "created_at"]},
            "products": {"columns": ["id", "name", "category", "price"]},
            "customers": {"columns": ["id", "name", "email", "region"]},
        }
    },
    tenant_glossary=[
        {"term": "GMV", "synonyms": ["gross merchandise value"]},
        {"term": "AOV", "synonyms": ["average order value"]},
    ],
    description="Retail analytics for orders, products, and customer insights",
    tenant_id="acme",
)
```

### LLM-Assisted Mode

```python
output = await gen.generate(
    schema_catalog=schema,
    tenant_glossary=glossary,
    description="Revenue analytics with churn prediction",
    llm_service=my_llm_service,  # Pass your LLM service
    tenant_id="acme",
)
```

Falls back to template mode if LLM fails.

## Generator Output

```python
output.skill_spec       # SkillSpec (always draft)
output.eval_dataset     # List[EvalExpectation] (≥10 questions)
output.risk_checklist   # List[RiskChecklistItem]
output.compilation_result  # CompilationResult (success/errors)
output.warnings         # List[str]
```

### Risk Checklist

The generator produces a risk assessment:

| Category           | Example                                                               |
| ------------------ | --------------------------------------------------------------------- |
| `data_access`      | "Skill may access data from tables: orders, products"                 |
| `tenant_isolation` | "No required tenant filter. Data from all tenants may be accessible." |
| `eval_coverage`    | "Only 10 eval questions. Consider adding more."                       |

## Safety Guarantees

1. **Always draft** — `spec.environment` is forced to `DRAFT` regardless of input
2. **Auto-validated** — the compiler validates the generated spec immediately
3. **Safe defaults** — `read_only=True`, `forbid_ddl_dml=True`
4. **Tenant predicate** — auto-adds `tenant_id` filter when `tenant_id` is provided
5. **No auto-publish** — human review + eval + RBAC required for promotion

## API Endpoint

```
POST /api/v1/skills/generate

{
  "description": "Retail analytics for orders and products",
  "schema_catalog": { "tables": { ... } },
  "tenant_glossary": [ { "term": "GMV", ... } ]
}
```

Response includes the proposed spec, eval questions, risk checklist, and compilation status.
