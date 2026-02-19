# Glossary & Ontology

The glossary system provides tenant-scoped term definitions that are injected into the LLM system prompt. This ensures the LLM uses the correct domain-specific terminology when generating SQL and interpreting user questions.

## Overview

- **Tenant-level** terms apply to all users in an organization
- **User-level** overrides allow individual customization
- Only **approved** entries are injected into the system prompt
- Terms include **synonyms** so the LLM recognizes alternative names

## Creating Entries

```python
from vanna.personalization.services import GlossaryService
from vanna.personalization.stores import InMemoryGlossaryStore
from vanna.personalization.models import GlossaryEntry

store = InMemoryGlossaryStore()
service = GlossaryService(store)

await service.create_entry(
    GlossaryEntry(
        tenant_id="acme",
        term="GMV",
        synonyms=["gross merchandise value", "total sales value"],
        definition="SUM(order_total) WHERE status != 'cancelled'",
        category="metric",
    ),
    requesting_user_id="admin1",
)
```

## How Glossary Is Injected

When the `PreferenceResolverEnhancer` runs, approved glossary entries are formatted as:

```
## Glossary / Ontology
- **GMV** (also: gross merchandise value, total sales value): SUM(order_total) WHERE status != 'cancelled'
- **AOV** (also: average order value): AVG(order_total) WHERE status != 'cancelled'
```

This block is appended to the system prompt, ensuring the LLM:

- Recognizes synonyms ("gross merchandise value" → GMV)
- Uses the correct SQL expression for metrics
- Applies the right business logic

## API Endpoints

| Method   | Path                    | Description               |
| -------- | ----------------------- | ------------------------- |
| `GET`    | `/api/v1/glossary`      | List entries for tenant   |
| `POST`   | `/api/v1/glossary`      | Create new entry          |
| `PUT`    | `/api/v1/glossary/{id}` | Update entry              |
| `DELETE` | `/api/v1/glossary/{id}` | Delete entry (admin only) |

## Approval Workflow

1. Any user can **create** a glossary entry (created as `approved=False`)
2. Admins approve entries (set `approved=True`)
3. Only approved entries are injected into the system prompt

## RBAC

- Any authenticated user can create entries
- Only the original author or an admin can update entries
- Only admins can delete entries
- All users can read/search entries within their tenant
