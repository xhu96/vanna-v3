"""
End-to-end integration test for personalization + skill fabric pipeline.

Tests the full workflow:
  1. Create tenant + user profiles with consent
  2. Add glossary entries
  3. Register, compile, and promote a skill
  4. Select skill for a question via the router
  5. Inject preferences + skill context into system prompt
  6. Verify entire pipeline produces correct output
"""

import asyncio
import pytest

from vanna.personalization.models import (
    GlossaryEntry,
    TenantProfile,
    UserProfile,
)
from vanna.personalization.preference_resolver import PreferenceResolverEnhancer
from vanna.personalization.services import (
    ConsentManager,
    GlossaryService,
    ProfileService,
)
from vanna.personalization.session_memory import SessionMemoryService
from vanna.personalization.stores import (
    InMemoryGlossaryStore,
    InMemoryProfileStore,
    InMemorySessionMemoryStore,
)
from vanna.skills.approval import ApprovalWorkflow
from vanna.skills.compiler import SkillCompiler
from vanna.skills.generator import SkillGenerator
from vanna.skills.models import (
    IntentTrigger,
    KnowledgeMapping,
    SkillEnvironment,
    SkillPolicy,
    SkillProvenance,
    SkillSpec,
    SqlLimits,
    EvalSuite,
    EvalExpectation,
)
from vanna.skills.registry import SkillRegistry
from vanna.skills.router import SkillRouter
from vanna.skills.stores import InMemorySkillRegistryStore

from unittest.mock import MagicMock


def _make_user(user_id="alice", tenant_id="acme"):
    user = MagicMock()
    user.id = user_id
    user.tenant_id = tenant_id
    return user


class TestE2EPersonalizationSkills:
    """Full pipeline: personalization + skills working together."""

    def test_full_pipeline(self):
        """End-to-end: profiles → glossary → skill → router → preference injection."""

        async def run():
            # --- Setup stores ---
            profile_store = InMemoryProfileStore()
            glossary_store = InMemoryGlossaryStore()
            session_store = InMemorySessionMemoryStore()
            skill_store = InMemorySkillRegistryStore()

            # --- Setup services ---
            profile_svc = ProfileService(profile_store)
            glossary_svc = GlossaryService(glossary_store)
            consent_mgr = ConsentManager(profile_store)
            session_svc = SessionMemoryService(session_store, retention_days=7)
            compiler = SkillCompiler()
            registry = SkillRegistry(skill_store)
            workflow = ApprovalWorkflow(registry, compiler, eval_required=True)
            router = SkillRouter(min_match_score=0.1)
            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)

            # ===== Step 1: Create tenant profile =====
            await profile_svc.upsert_tenant_profile(
                TenantProfile(
                    tenant_id="acme",
                    personalization_enabled=True,
                    default_locale="en-US",
                    default_currency="USD",
                ),
                requesting_user_groups=["admin"],
            )

            # ===== Step 2: Set user preferences =====
            await profile_svc.upsert_user_profile(
                UserProfile(
                    user_id="alice",
                    tenant_id="acme",
                    locale="en-GB",
                    currency="GBP",
                    date_format="DD/MM/YYYY",
                    department_tags=["finance"],
                    role_tags=["analyst"],
                    preferred_chart_type="bar",
                ),
                requesting_user_id="alice",
            )

            # ===== Step 3: User opts in (after profile exists) =====
            await consent_mgr.enable_personalization("alice", "acme")

            # ===== Step 4: Add glossary entries =====
            await glossary_svc.create_entry(
                GlossaryEntry(
                    tenant_id="acme",
                    term="GMV",
                    synonyms=["gross merchandise value"],
                    definition="SUM(order_total) WHERE status != 'cancelled'",
                    category="metric",
                    approved=True,
                ),
                requesting_user_id="admin",
            )
            await glossary_svc.create_entry(
                GlossaryEntry(
                    tenant_id="acme",
                    term="AOV",
                    synonyms=["average order value"],
                    definition="AVG(order_total) WHERE status != 'cancelled'",
                    category="metric",
                    approved=True,
                ),
                requesting_user_id="admin",
            )

            # ===== Step 5: Save session memory =====
            await session_svc.save(
                session_id="s1",
                user_id="alice",
                tenant_id="acme",
                content="Last question was about Q4 revenue",
            )
            recent = await session_svc.get_recent("alice", "s1")
            assert len(recent) == 1
            assert "Q4 revenue" in recent[0].content

            # ===== Step 6: Register a skill =====
            spec = SkillSpec(
                name="retail_analytics",
                version="1.0.0",
                tenant_id="acme",
                description="Retail analytics for orders and products",
                provenance=SkillProvenance(author="admin"),
                intents=IntentTrigger(
                    patterns=[r"(?i)\b(revenue|sales|order|GMV|AOV)\b"],
                    embedding_hints=["total revenue", "order analysis"],
                    tool_routing_hints=["run_sql"],
                ),
                knowledge=KnowledgeMapping(
                    synonyms={"revenue": ["sales", "turnover"]},
                    metric_definitions={
                        "GMV": "SUM(order_total) WHERE status != 'cancelled'",
                    },
                ),
                policies=SkillPolicy(
                    required_filters=["tenant_id = :tenant_id"],
                    column_redaction_rules=["credit_card_number"],
                    sql_limits=SqlLimits(
                        read_only=True,
                        max_rows=1000,
                        require_limit=True,
                        forbid_ddl_dml=True,
                    ),
                ),
                eval_suite=EvalSuite(
                    pass_rate_threshold=0.8,
                    min_score=0.7,
                    inline_evals=[
                        EvalExpectation(
                            question="What was total revenue?",
                            constraints=["uses SUM"],
                        ),
                    ],
                ),
            )
            entry = await registry.register_skill(spec, actor="admin", tenant_id="acme")
            assert entry.environment == SkillEnvironment.DRAFT

            # ===== Step 7: Compile the skill =====
            compilation = await workflow.compile_skill(entry.skill_id)
            assert compilation.success, f"Compilation failed: {compilation.errors}"

            # ===== Step 8: Promote draft → tested → approved =====
            entry = await workflow.promote(
                entry.skill_id,
                SkillEnvironment.TESTED,
                actor="admin",
                actor_groups=["admin"],
            )
            assert entry.environment == SkillEnvironment.TESTED

            entry = await workflow.promote(
                entry.skill_id,
                SkillEnvironment.APPROVED,
                actor="admin",
                actor_groups=["admin"],
                eval_results={"pass_rate": 0.95, "average_score": 0.88},
            )
            assert entry.environment == SkillEnvironment.APPROVED

            # ===== Step 9: Route question to skill =====
            all_skills = await registry.list_skills(
                tenant_id="acme", enabled_only=True
            )
            selected = router.select_skills(
                "What was total revenue last month?",
                all_skills,
            )
            assert len(selected) >= 1
            assert selected[0].skill_name == "retail_analytics"

            # Merge skill context
            merged = SkillRouter.merge_skill_context(selected)
            assert "revenue" in merged["glossary"]
            assert "tenant_id = :tenant_id" in merged["policy_constraints"]["required_filters"]

            # ===== Step 10: System prompt injection =====
            user = _make_user("alice", "acme")
            system_prompt = await enhancer.enhance_system_prompt(
                "You are an analytics assistant.",
                "What was total revenue last month?",
                user,
            )

            # Verify preferences injected
            assert "Locale: en-GB" in system_prompt
            assert "Currency: GBP" in system_prompt
            assert "DD/MM/YYYY" in system_prompt

            # Verify glossary injected
            assert "GMV" in system_prompt
            assert "gross merchandise value" in system_prompt
            assert "AOV" in system_prompt

            # Verify original prompt preserved
            assert "You are an analytics assistant." in system_prompt

            # ===== Step 11: Verify audit trail =====
            audit_log = await registry.get_audit_log(entry.skill_id)
            actions = [a.action for a in audit_log]
            assert "created" in actions
            assert "promoted" in actions
            assert len(audit_log) >= 3  # created + 2 promotions

            return True

        result = asyncio.run(run())
        assert result is True

    def test_skill_generation_and_registration(self):
        """E2E: generate a skill from schema → register → compile → verify."""

        async def run():
            # Setup
            compiler = SkillCompiler()
            generator = SkillGenerator(compiler=compiler)
            store = InMemorySkillRegistryStore()
            registry = SkillRegistry(store)

            # Generate a skill
            output = await generator.generate(
                schema_catalog={
                    "tables": {
                        "invoices": {"columns": ["id", "customer_id", "amount", "date"]},
                        "customers": {"columns": ["id", "name", "region"]},
                    }
                },
                tenant_glossary=[
                    {"term": "Revenue", "synonyms": ["sales", "turnover"]},
                ],
                description="Invoice analytics with customer breakdown",
                tenant_id="acme",
            )

            # Verify generator output
            assert output.skill_spec.environment == SkillEnvironment.DRAFT
            assert len(output.eval_dataset) >= 10
            assert len(output.risk_checklist) > 0
            assert output.compilation_result is not None
            assert output.compilation_result.success

            # Register generated skill
            entry = await registry.register_skill(
                output.skill_spec, actor="generator", tenant_id="acme"
            )
            assert entry.skill_id is not None
            assert entry.environment == SkillEnvironment.DRAFT

            # Compile via registry
            result = compiler.compile(entry.skill_spec)
            assert result.success

            return True

        result = asyncio.run(run())
        assert result is True

    def test_disabled_personalization_clean_prompt(self):
        """E2E: when personalization is disabled, system prompt is untouched."""

        async def run():
            profile_store = InMemoryProfileStore()
            glossary_store = InMemoryGlossaryStore()
            enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)

            # Tenant exists but personalization disabled
            await profile_store.upsert_tenant_profile(
                TenantProfile(tenant_id="acme", personalization_enabled=False)
            )

            user = _make_user("alice", "acme")
            prompt = "You are an assistant."
            result = await enhancer.enhance_system_prompt(prompt, "question", user)

            # Prompt should be completely untouched
            assert result == prompt

            return True

        result = asyncio.run(run())
        assert result is True

    def test_skill_rollback_restores_environment(self):
        """E2E: promote a skill, then rollback and verify environment restored."""

        async def run():
            store = InMemorySkillRegistryStore()
            registry = SkillRegistry(store)
            compiler = SkillCompiler()
            workflow = ApprovalWorkflow(registry, compiler, eval_required=False)

            spec = SkillSpec(
                name="rollback_test",
                provenance=SkillProvenance(author="admin"),
            )
            entry = await registry.register_skill(spec, actor="admin")

            # Promote to tested
            entry = await workflow.promote(
                entry.skill_id,
                SkillEnvironment.TESTED,
                actor="admin",
                actor_groups=["admin"],
            )
            assert entry.environment == SkillEnvironment.TESTED

            # Rollback to draft
            entry = await registry.rollback_skill(
                entry.skill_id,
                SkillEnvironment.DRAFT,
                actor="admin",
                actor_groups=["admin"],
            )
            assert entry.environment == SkillEnvironment.DRAFT

            # Verify audit log shows rollback
            log = await registry.get_audit_log(entry.skill_id)
            actions = [a.action for a in log]
            assert "rolled_back" in actions

            return True

        result = asyncio.run(run())
        assert result is True
