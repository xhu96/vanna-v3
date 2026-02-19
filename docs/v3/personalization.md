# Personalization & User Profiles

Vanna v3 supports privacy-safe user and tenant personalization. When enabled, user preferences (locale, currency, date format, department tags) are injected deterministically into the LLM system prompt — **no fuzzy retrieval or embedding search** is used.

## How It Works

```
User Request → PreferenceResolverEnhancer → System Prompt Injection → LLM
                      ↓
              ProfileStore + GlossaryStore
```

1. Load **tenant profile** defaults (locale, currency, date format, etc.)
2. Overlay **user profile** overrides
3. Append **active glossary terms** for the tenant (+ user overrides)
4. Format as structured text block appended to system prompt

## Enabling Personalization

Personalization is **double opt-in**: both the tenant AND the user must explicitly enable it.

### 1. Tenant Admin enables for the org

```python
from vanna.personalization.services import ProfileService, ConsentManager
from vanna.personalization.stores import InMemoryProfileStore
from vanna.personalization.models import TenantProfile

store = InMemoryProfileStore()
service = ProfileService(store)

await service.upsert_tenant_profile(
    TenantProfile(
        tenant_id="acme",
        personalization_enabled=True,
        default_locale="en-US",
        default_currency="USD",
    ),
    requesting_user_groups=["admin"],
)
```

### 2. User opts in

```python
consent = ConsentManager(store)
await consent.enable_personalization("user123", "acme")
```

### 3. Set user preferences

```python
from vanna.personalization.models import UserProfile

await service.upsert_user_profile(
    UserProfile(
        user_id="user123",
        tenant_id="acme",
        locale="en-GB",
        currency="GBP",
        date_format="DD/MM/YYYY",
        department_tags=["finance"],
        role_tags=["analyst"],
        preferred_chart_type="bar",
    ),
    requesting_user_id="user123",
)
```

## Configuration

In `AgentConfig`:

| Setting                         | Default | Description                           |
| ------------------------------- | ------- | ------------------------------------- |
| `enable_personalization`        | `False` | Master switch (tenant default)        |
| `session_memory_retention_days` | `7`     | Days to keep ephemeral session memory |

## Privacy Guarantees

- **PII redaction**: All text fields are scanned for emails, phones, SSNs, API keys, and credit card numbers before storage
- **Storage policy**: Raw query results are rejected from profile storage
- **Provenance tracking**: Every change records author, source, and timestamp
- **Data export**: Users can export all stored data (`GET /api/v1/profile/export`)
- **Data deletion**: Users can delete all stored data (`DELETE /api/v1/profile`)
- **Session memory**: Ephemeral with configurable TTL — auto-expires

## API Endpoints

| Method   | Path                      | Description                   |
| -------- | ------------------------- | ----------------------------- |
| `GET`    | `/api/v1/profile`         | Get current user's profile    |
| `PUT`    | `/api/v1/profile`         | Create/update profile         |
| `DELETE` | `/api/v1/profile`         | Delete profile                |
| `GET`    | `/api/v1/profile/export`  | Export all profile data       |
| `PUT`    | `/api/v1/tenant/profile`  | Update tenant profile (admin) |
| `POST`   | `/api/v1/consent/enable`  | Opt in to personalization     |
| `POST`   | `/api/v1/consent/disable` | Opt out                       |

All endpoints authenticate via `X-User-Id`, `X-Tenant-Id`, and `X-User-Groups` headers.

## RBAC Rules

- Users can only read/update/delete **their own** profile
- Admins can read/update any profile
- Tenant profile updates require `admin` role
- User consent is self-service (no admin required)
