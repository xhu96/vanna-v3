# uk_accounting

A sample skill pack for UK accounting and financial reporting.

## What's Included

| File                | Description                                              |
| ------------------- | -------------------------------------------------------- |
| `skill.yaml`        | SkillSpec with UK accounting intents, glossary, policies |
| `eval_dataset.yaml` | 15 constraint-based evaluation questions                 |

## UK-specific Glossary

- **P&L** (Profit & Loss) — income statement
- **VAT** — Value Added Tax
- **HMRC** — HM Revenue & Customs
- **PAYE** — Pay As You Earn
- **NI/NIC** — National Insurance Contributions
- **Debtors** — accounts receivable / trade debtors
- **Creditors** — accounts payable / trade creditors
- **Turnover** — revenue / sales / income

## Rendering Defaults

- **Currency**: GBP (£)
- **Locale**: en-GB
- **Date format**: DD/MM/YYYY

## Policies

- **Read-only SQL** (no INSERT/UPDATE/DELETE/DDL)
- **Tenant isolation**: `tenant_id = :tenant_id`
- **Column redaction**: bank_account_number, sort_code, ni_number
- **Row limit**: 500 rows max
