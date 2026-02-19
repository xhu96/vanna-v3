"""Golden path: Personalization + Skill Fabric with FastAPI.

Demonstrates:
  - Tenant/user profile creation with consent
  - Glossary setup
  - Skill pack loading, compilation, and promotion
  - Preference resolver wired into the agent
  - Skill router wired into the agent
"""

import yaml
from vanna import Agent, AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mock import MockLlmService
from vanna.integrations.sqlite import SqliteRunner
from vanna.personalization.models import GlossaryEntry, TenantProfile, UserProfile
from vanna.personalization.preference_resolver import PreferenceResolverEnhancer
from vanna.personalization.services import ConsentManager, GlossaryService, ProfileService
from vanna.personalization.stores import InMemoryGlossaryStore, InMemoryProfileStore
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.skills.compiler import SkillCompiler
from vanna.skills.models import SkillEnvironment, SkillSpec
from vanna.skills.registry import SkillRegistry
from vanna.skills.router import SkillRouter
from vanna.skills.stores import InMemorySkillRegistryStore
from vanna.tools import RunSqlTool


class DemoUserResolver(UserResolver):
    """Simple resolver that returns a tenant-scoped user."""

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="alice",
            email="alice@acme.com",
            tenant_id="acme",
            group_memberships=["user", "admin"],
        )


async def setup_personalization():
    """Set up tenant, user profile, glossary, and consent."""
    profile_store = InMemoryProfileStore()
    glossary_store = InMemoryGlossaryStore()

    profile_svc = ProfileService(profile_store)
    glossary_svc = GlossaryService(glossary_store)
    consent_mgr = ConsentManager(profile_store)

    # 1. Create tenant with personalization enabled
    await profile_svc.upsert_tenant_profile(
        TenantProfile(
            tenant_id="acme",
            personalization_enabled=True,
            default_locale="en-US",
            default_currency="USD",
        ),
        requesting_user_groups=["admin"],
    )

    # 2. Set user preferences
    await profile_svc.upsert_user_profile(
        UserProfile(
            user_id="alice",
            tenant_id="acme",
            locale="en-GB",
            currency="GBP",
            date_format="DD/MM/YYYY",
            department_tags=["finance"],
        ),
        requesting_user_id="alice",
    )

    # 3. Opt in
    await consent_mgr.enable_personalization("alice", "acme")

    # 4. Add glossary terms
    for term, defn, syns in [
        ("GMV", "SUM(order_total) WHERE status != 'cancelled'", ["gross merchandise value"]),
        ("AOV", "AVG(order_total) WHERE status != 'cancelled'", ["average order value"]),
    ]:
        await glossary_svc.create_entry(
            GlossaryEntry(
                tenant_id="acme", term=term, definition=defn,
                synonyms=syns, category="metric", approved=True,
            ),
            requesting_user_id="admin",
        )

    return profile_store, glossary_store


async def setup_skills():
    """Load a skill pack, compile, and promote to approved."""
    store = InMemorySkillRegistryStore()
    registry = SkillRegistry(store)
    compiler = SkillCompiler()

    # Load skill pack from YAML
    with open("skill_packs/retail_ops_basics/skill.yaml") as f:
        spec = SkillSpec(**yaml.safe_load(f))

    # Compile (deterministic validation)
    result = compiler.compile(spec)
    assert result.success, f"Compilation failed: {result.errors}"

    # Register as draft
    entry = await registry.register_skill(spec, actor="admin", tenant_id="acme")
    print(f"✅ Registered skill: {entry.skill_spec.name} (draft)")

    # Promote draft → tested → approved
    entry = await registry.promote_skill(
        entry.skill_id, SkillEnvironment.TESTED,
        actor="admin", actor_groups=["admin"],
    )
    entry = await registry.promote_skill(
        entry.skill_id, SkillEnvironment.APPROVED,
        actor="admin", actor_groups=["admin"],
    )
    print(f"✅ Promoted to: {entry.environment.value}")

    return store, registry


async def main() -> None:
    # --- Setup personalization ---
    profile_store, glossary_store = await setup_personalization()
    enhancer = PreferenceResolverEnhancer(profile_store, glossary_store)
    print("✅ Personalization ready (tenant + user + glossary)")

    # --- Setup skills ---
    skill_store, registry = await setup_skills()
    router = SkillRouter(min_match_score=0.1)

    # --- Demo: route a question ---
    all_skills = await registry.list_skills(tenant_id="acme", enabled_only=True)
    selected = router.select_skills("What was total revenue last month?", all_skills)
    print(f"✅ Router matched {len(selected)} skill(s): {[s.skill_name for s in selected]}")

    # --- Demo: preference injection ---
    from unittest.mock import MagicMock
    user = MagicMock()
    user.id = "alice"
    user.tenant_id = "acme"

    prompt = await enhancer.enhance_system_prompt(
        "You are an analytics assistant.", "What was GMV?", user
    )
    print(f"✅ Enhanced prompt ({len(prompt)} chars)")
    print("---")
    print(prompt[:500])
    print("---")

    # --- Setup agent + server ---
    sql_runner = SqliteRunner(database_path="./Chinook.sqlite")
    tools = ToolRegistry()
    tools.register_local_tool(RunSqlTool(sql_runner=sql_runner, read_only=True), ["user"])

    agent = Agent(
        llm_service=MockLlmService(),
        tool_registry=tools,
        user_resolver=DemoUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            enable_personalization=True,
            enable_skill_generation=False,
        ),
        context_enhancers=[enhancer],
    )

    server = VannaFastAPIServer(agent=agent)
    print("\n🚀 Starting server on http://localhost:8765")
    print("   Personalization: enabled (alice@acme, en-GB, GBP)")
    print("   Skills: retail_ops_basics (approved)")
    server.run(port=8765)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
