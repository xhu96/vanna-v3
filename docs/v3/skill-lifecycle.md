# Skill Lifecycle & Governance

Skills follow a strict lifecycle with RBAC, eval gates, and full audit logging.

## State Machine

```
  draft  ──→  tested  ──→  approved  ──→  default
    ↑            │              │             │
    └────────────┴──────────────┴─────────────┘
                     (rollback)
```

| Transition         | Requirements                                                                |
| ------------------ | --------------------------------------------------------------------------- |
| → draft            | Any authenticated user (registration)                                       |
| draft → tested     | Publisher role (`allow_skill_publish_roles`)                                |
| tested → approved  | Publisher role + eval suite must pass `pass_rate_threshold` and `min_score` |
| approved → default | Publisher role + eval suite must pass                                       |
| Any rollback       | Publisher role                                                              |

## Promotion Flow

```python
from vanna.skills.approval import ApprovalWorkflow
from vanna.skills.compiler import SkillCompiler
from vanna.skills.registry import SkillRegistry
from vanna.skills.stores import InMemorySkillRegistryStore
from vanna.skills.models import SkillEnvironment

store = InMemorySkillRegistryStore()
registry = SkillRegistry(store, publish_roles=["admin", "skill_admin"])
compiler = SkillCompiler()
workflow = ApprovalWorkflow(registry, compiler, eval_required=True)

# 1. Register (always draft)
entry = await registry.register_skill(spec, actor="alice")

# 2. Compile (validate without promoting)
result = await workflow.compile_skill(entry.skill_id)
assert result.success

# 3. Promote draft → tested (role check only)
entry = await workflow.promote(
    entry.skill_id,
    SkillEnvironment.TESTED,
    actor="admin",
    actor_groups=["admin"],
)

# 4. Promote tested → approved (requires eval results)
entry = await workflow.promote(
    entry.skill_id,
    SkillEnvironment.APPROVED,
    actor="admin",
    actor_groups=["admin"],
    eval_results={"pass_rate": 0.92, "average_score": 0.85},
)
```

## Three Validation Gates

1. **Compiler** — SkillSpec must pass all deterministic validation rules
2. **Eval Suite** — Pass rate and average score must meet thresholds (for `approved`/`default`)
3. **RBAC** — Actor must have appropriate role membership

## Rollback

```python
entry = await registry.rollback_skill(
    entry.skill_id,
    SkillEnvironment.DRAFT,
    actor="admin",
    actor_groups=["admin"],
)
```

Rollback can go to any **previous** environment. It requires the publisher role.

## Audit Log

Every state transition is recorded:

```python
log = await registry.get_audit_log(skill_id)
# [
#   SkillAuditEntry(action="created", actor="alice", to_env="draft", ...),
#   SkillAuditEntry(action="promoted", actor="admin", from_env="draft", to_env="tested", ...),
#   SkillAuditEntry(action="promoted", actor="admin", from_env="tested", to_env="approved", ...),
# ]
```

## API Endpoints

| Method   | Path                           | Description                |
| -------- | ------------------------------ | -------------------------- |
| `POST`   | `/api/v1/skills`               | Register new skill (draft) |
| `POST`   | `/api/v1/skills/{id}/compile`  | Compile/validate           |
| `POST`   | `/api/v1/skills/{id}/promote`  | Promote to next env        |
| `POST`   | `/api/v1/skills/{id}/rollback` | Rollback to previous env   |
| `PUT`    | `/api/v1/skills/{id}/enable`   | Enable skill               |
| `PUT`    | `/api/v1/skills/{id}/disable`  | Disable skill              |
| `DELETE` | `/api/v1/skills/{id}`          | Delete skill (admin)       |
| `GET`    | `/api/v1/skills/{id}/audit`    | View audit log             |
