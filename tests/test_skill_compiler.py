"""Tests for the Skill Compiler."""

from vanna.skills.compiler import SkillCompiler
from vanna.skills.models import (
    SkillSpec, SkillProvenance, SkillPolicy, SqlLimits,
    IntentTrigger, EvalSuite, EvalExpectation,
)


class TestSkillCompiler:
    def test_valid_spec_compiles(self):
        compiler = SkillCompiler()
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="me"))
        result = compiler.compile(spec)
        assert result.success
        assert result.compiled_skill is not None
        assert len(result.errors) == 0

    def test_rejects_write_sql(self):
        compiler = SkillCompiler()
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            policies=SkillPolicy(sql_limits=SqlLimits(read_only=False)),
        )
        result = compiler.compile(spec)
        assert not result.success
        assert any("read_only" in e for e in result.errors)

    def test_rejects_ddl_dml(self):
        compiler = SkillCompiler()
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            policies=SkillPolicy(sql_limits=SqlLimits(forbid_ddl_dml=False)),
        )
        result = compiler.compile(spec)
        assert not result.success
        assert any("forbid_ddl_dml" in e for e in result.errors)

    def test_rejects_missing_tenant_predicate(self):
        compiler = SkillCompiler(require_tenant_predicate=True)
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="me"))
        result = compiler.compile(spec)
        assert not result.success
        assert any("tenant predicate" in e for e in result.errors)

    def test_accepts_with_tenant_predicate(self):
        compiler = SkillCompiler(require_tenant_predicate=True)
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            policies=SkillPolicy(required_filters=["tenant_id = :tid"]),
        )
        result = compiler.compile(spec)
        assert result.success

    def test_rejects_unknown_tool(self):
        compiler = SkillCompiler(known_tools=["run_sql", "search"])
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            policies=SkillPolicy(tool_allowlist=["run_sql", "nonexistent"]),
        )
        result = compiler.compile(spec)
        assert not result.success
        assert any("nonexistent" in e for e in result.errors)

    def test_rejects_conflicting_allow_deny(self):
        compiler = SkillCompiler()
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            policies=SkillPolicy(
                tool_allowlist=["run_sql"],
                tool_denylist=["run_sql"],
            ),
        )
        result = compiler.compile(spec)
        assert not result.success
        assert any("allowlist and denylist" in e for e in result.errors)

    def test_rejects_invalid_regex(self):
        compiler = SkillCompiler()
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            intents=IntentTrigger(patterns=["[invalid"]),
        )
        result = compiler.compile(spec)
        assert not result.success
        assert any("Invalid regex" in e for e in result.errors)

    def test_warns_no_intents(self):
        compiler = SkillCompiler()
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="me"))
        result = compiler.compile(spec)
        assert result.success  # Warnings don't block compilation
        assert any("discoverable" in w for w in result.warnings)

    def test_warns_no_eval(self):
        compiler = SkillCompiler()
        spec = SkillSpec(name="test", provenance=SkillProvenance(author="me"))
        result = compiler.compile(spec)
        assert any("eval suite" in w.lower() for w in result.warnings)

    def test_deterministic_compilation(self):
        compiler = SkillCompiler()
        spec = SkillSpec(
            name="test",
            provenance=SkillProvenance(author="me"),
            intents=IntentTrigger(patterns=["(?i)revenue"]),
        )
        r1 = compiler.compile(spec)
        r2 = compiler.compile(spec)
        assert r1.compiled_skill.skill_spec_hash == r2.compiled_skill.skill_spec_hash

    def test_rejects_empty_name(self):
        compiler = SkillCompiler()
        spec = SkillSpec(name="", provenance=SkillProvenance(author="me"))
        result = compiler.compile(spec)
        assert not result.success
        assert any("name" in e.lower() for e in result.errors)
