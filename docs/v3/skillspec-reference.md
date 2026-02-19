# SkillSpec Reference

A `SkillSpec` is a declarative YAML/JSON document that defines a skill's behavior without code. Skills contribute context to the LLM — they never execute code or bypass existing guardrails.

## Full Schema

```yaml
name: string # Required. Unique skill name
version: "1.0.0" # Semantic version
tenant_id: string | null # Tenant scope (null = global)
environment: draft|tested|approved|default
description: string # Human-readable description

provenance:
  author: string # Who created this spec
  source: string # Origin (api, generator, manual)
  timestamp: ISO-8601
  generator_metadata: {} # If LLM-generated

intents:
  patterns: # Regex patterns for question matching
    - "(?i)\\b(revenue|sales)\\b"
  embedding_hints: # Keywords for semantic matching
    - "total revenue by month"
  tool_routing_hints: # Preferred tools
    - "run_sql"

knowledge:
  synonyms: # Term → alternative names
    revenue: [sales, turnover]
  metric_definitions: # Metric → SQL expression
    GMV: "SUM(order_total) WHERE status != 'cancelled'"
  semantic_mappings: # Concept → column/expression
    customer_name: "customers.full_name"

policies:
  tool_allowlist: [] # Only these tools may be used
  tool_denylist: [] # These tools are forbidden
  required_filters: # WHERE clause fragments always applied
    - "tenant_id = :tenant_id"
  row_redaction_rules: [] # Row-level filtering rules
  column_redaction_rules: # Columns to never expose
    - "credit_card_number"
    - "ssn"
  sql_limits:
    read_only: true # MUST be true (enforced by compiler)
    max_rows: 1000
    max_runtime_seconds: 30 # Optional
    require_limit: true
    forbid_ddl_dml: true # MUST be true (enforced by compiler)

rendering:
  currency: USD
  locale: en-US
  date_format: "YYYY-MM-DD"
  number_format: "1,000.00"
  fiscal_year_start_month: 1
  preferred_output_layout: table|chart|auto

eval_suite:
  pass_rate_threshold: 0.8 # Required pass rate for promotion
  min_score: 0.7 # Minimum average score
  eval_data_path: null # Path to external eval dataset
  inline_evals: # Inline eval questions
    - question: "What was total revenue?"
      constraints:
        - "uses SUM on revenue column"
        - "returns numeric value"
      expected_tool: run_sql
      tags: [revenue]
```

## Compiler Validation Rules

The `SkillCompiler` enforces these rules **deterministically** (no LLM):

| Rule                                           | Error                                            |
| ---------------------------------------------- | ------------------------------------------------ |
| `sql_limits.read_only` must be `true`          | "Skills cannot enable write SQL"                 |
| `sql_limits.forbid_ddl_dml` must be `true`     | "Skills cannot allow DDL/DML"                    |
| `tool_allowlist ∩ tool_denylist` must be empty | "Tools cannot appear in both"                    |
| Intent patterns must be valid regex            | "Invalid regex pattern"                          |
| Tenant predicate required (when configured)    | "required_filters must contain tenant predicate" |

## Security Invariant

> **Skills can only ADD policy constraints — they can NEVER remove or override existing guardrails.**

When multiple skills apply to a question, their policies are merged as the **union of restrictions**: denylists are combined, required filters are combined, and numeric limits use the strictest value.
