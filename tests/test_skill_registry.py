"""Tests for the Skill Registry."""

import pytest
import asyncio
from vanna.skills.registry import (
    SkillRegistry, SkillRegistryError, SkillAuthorizationError,
)
from vanna.skills.models import SkillSpec, SkillProvenance, SkillEnvironment
from vanna.skills.stores import InMemorySkillRegistryStore


@pytest.fixture
def registry():
    store = InMemorySkillRegistryStore()
    return SkillRegistry(store)


def _make_spec(name="test"):
    return SkillSpec(name=name, provenance=SkillProvenance(author="test"))


class TestSkillRegistry:
    def test_register_creates_draft(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            assert entry.environment == SkillEnvironment.DRAFT
            assert entry.enabled is True
            assert len(entry.audit_log) == 1
            assert entry.audit_log[0].action == "created"

        asyncio.run(run())

    def test_list_and_get(self, registry):
        async def run():
            e1 = await registry.register_skill(_make_spec("a"), actor="alice")
            e2 = await registry.register_skill(_make_spec("b"), actor="alice")
            all_skills = await registry.list_skills()
            assert len(all_skills) == 2

            fetched = await registry.get_skill(e1.skill_id)
            assert fetched is not None
            assert fetched.skill_spec.name == "a"

        asyncio.run(run())

    def test_enable_disable(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            disabled = await registry.disable_skill(entry.skill_id, actor="alice")
            assert disabled.enabled is False

            enabled = await registry.enable_skill(entry.skill_id, actor="alice")
            assert enabled.enabled is True

        asyncio.run(run())

    def test_promote_sequential(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            # draft → tested
            entry = await registry.promote_skill(
                entry.skill_id, SkillEnvironment.TESTED,
                actor="admin", actor_groups=["admin"],
            )
            assert entry.environment == SkillEnvironment.TESTED

            # tested → approved
            entry = await registry.promote_skill(
                entry.skill_id, SkillEnvironment.APPROVED,
                actor="admin", actor_groups=["admin"],
            )
            assert entry.environment == SkillEnvironment.APPROVED

        asyncio.run(run())

    def test_promote_skip_rejected(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            with pytest.raises(SkillRegistryError, match="Cannot promote"):
                await registry.promote_skill(
                    entry.skill_id, SkillEnvironment.APPROVED,
                    actor="admin", actor_groups=["admin"],
                )

        asyncio.run(run())

    def test_promote_requires_role(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            with pytest.raises(SkillAuthorizationError):
                await registry.promote_skill(
                    entry.skill_id, SkillEnvironment.TESTED,
                    actor="alice", actor_groups=["user"],
                )

        asyncio.run(run())

    def test_rollback(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            entry = await registry.promote_skill(
                entry.skill_id, SkillEnvironment.TESTED,
                actor="admin", actor_groups=["admin"],
            )
            entry = await registry.rollback_skill(
                entry.skill_id, SkillEnvironment.DRAFT,
                actor="admin", actor_groups=["admin"],
            )
            assert entry.environment == SkillEnvironment.DRAFT
            assert any(a.action == "rolled_back" for a in entry.audit_log)

        asyncio.run(run())

    def test_delete_requires_role(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            with pytest.raises(SkillAuthorizationError):
                await registry.delete_skill(
                    entry.skill_id, actor="alice", actor_groups=["user"],
                )

        asyncio.run(run())

    def test_audit_log(self, registry):
        async def run():
            entry = await registry.register_skill(_make_spec(), actor="alice")
            await registry.enable_skill(entry.skill_id, actor="bob")
            log = await registry.get_audit_log(entry.skill_id)
            assert len(log) >= 2

        asyncio.run(run())
