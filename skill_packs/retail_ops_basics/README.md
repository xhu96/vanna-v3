# retail_ops_basics

A sample skill pack for common retail operations analytics.

## What's Included

| File                | Description                                                        |
| ------------------- | ------------------------------------------------------------------ |
| `skill.yaml`        | SkillSpec with intents, glossary, policies, and rendering defaults |
| `eval_dataset.yaml` | 15 constraint-based evaluation questions                           |

## Glossary Terms

- **GMV** (Gross Merchandise Value) — `SUM(order_total) WHERE status != 'cancelled'`
- **AOV** (Average Order Value) — `AVG(order_total) WHERE status != 'cancelled'`
- **Refund Rate** — `COUNT(refunded) / COUNT(all)`
- **Margin** — `(SUM(revenue) - SUM(cost)) / SUM(revenue)`
- **SKU** — Stock Keeping Unit / product code
- **Churn** — Customer attrition rate

## Installation

```python
from vanna.skills.registry import SkillRegistry
from vanna.skills.compiler import SkillCompiler
import yaml

# Load the pack
with open("skill_packs/retail_ops_basics/skill.yaml") as f:
    spec_data = yaml.safe_load(f)

from vanna.skills.models import SkillSpec
spec = SkillSpec(**spec_data)

# Register
registry = SkillRegistry(store)
entry = await registry.register_skill(spec, actor="admin", tenant_id="my_tenant")

# Compile
compiler = SkillCompiler()
result = compiler.compile(spec)
assert result.success
```

## Policies

- **Read-only SQL** only (no INSERT/UPDATE/DELETE/DDL)
- **Tenant isolation**: requires `tenant_id = :tenant_id` filter
- **Column redaction**: credit_card_number, ssn, password
- **Row limit**: 1,000 rows max
- **LIMIT required**: enforced
