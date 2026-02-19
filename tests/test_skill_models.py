"""Tests for Skill Fabric Pydantic models."""

import pytest
from vanna.skills.models import (
    SkillSpec, CompiledSkill, SkillRegistryEntry, SkillAuditEntry,
    SkillEnvironment, SkillProvenance, IntentTrigger, KnowledgeMapping,
    SkillPolicy, SqlLimits, RenderingDefaults, EvalSuite, EvalExpectation,
    CompilationResult,
)


class TestSkillSpec:
    def test_create_minimal(self):
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="me"))
        assert spec.name == "test"
        assert spec.version == "1.0.0"
        assert spec.environment == SkillEnvironment.DRAFT

    def test_default_policy_is_safe(self):
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="me"))
        assert spec.policies.sql_limits.read_only is True
        assert spec.policies.sql_limits.forbid_ddl_dml is True

    def test_json_roundtrip(self):
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            intents=IntentTrigger(patterns=["(?i)\\brevenue\\b"]),
            knowledge=KnowledgeMapping(synonyms={"revenue": ["sales"]}),
        )
        data = spec.model_dump(mode="json")
        spec2 = SkillSpec(**data)
        assert spec2.name == spec.name
        assert spec2.intents.patterns == spec.intents.patterns

    def test_json_schema_generation(self):
        schema = SkillSpec.model_json_schema()
        assert "properties" in schema
        assert "name" in schema["properties"]

    def test_missing_name_empty_string(self):
        # Empty name is valid per Pydantic but compiler will reject
        spec = SkillSpec(name="", provenance=SkillProvenance(author="me"))
        assert spec.name == ""


class TestCompiledSkill:
    def test_compute_spec_hash_deterministic(self):
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="a"))
        h1 = CompiledSkill.compute_spec_hash(spec)
        h2 = CompiledSkill.compute_spec_hash(spec)
        assert h1 == h2

    def test_different_specs_different_hash(self):
        spec1 = SkillSpec(name="a", provenance=SkillProvenance(author="x"))
        spec2 = SkillSpec(name="b", provenance=SkillProvenance(author="x"))
        assert CompiledSkill.compute_spec_hash(spec1) != CompiledSkill.compute_spec_hash(spec2)


class TestSkillRegistryEntry:
    def test_auto_id(self):
        entry = SkillRegistryEntry(
            skill_spec=SkillSpec(name="t", provenance=SkillProvenance(author="a"))
        )
        assert entry.skill_id  # Should be auto-generated UUID


class TestSkillEnvironment:
    def test_values(self):
        assert SkillEnvironment.DRAFT.value == "draft"
        assert SkillEnvironment.TESTED.value == "tested"
        assert SkillEnvironment.APPROVED.value == "approved"
        assert SkillEnvironment.DEFAULT.value == "default"
