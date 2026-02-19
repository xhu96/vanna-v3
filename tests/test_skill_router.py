"""Tests for the Skill Router."""

from vanna.skills.router import SkillRouter, SelectedSkill
from vanna.skills.models import (
    SkillSpec, SkillProvenance, SkillRegistryEntry, IntentTrigger,
    CompiledSkill, KnowledgeMapping, SkillPolicy,
)
from vanna.skills.compiler import SkillCompiler


def _make_compiled_entry(name, patterns=None, hints=None, tool_hints=None):
    spec = SkillSpec(
        name=name,
        provenance=SkillProvenance(author="test"),
        intents=IntentTrigger(
            patterns=patterns or [],
            embedding_hints=hints or [],
            tool_routing_hints=tool_hints or [],
        ),
        knowledge=KnowledgeMapping(
            synonyms={"revenue": ["sales"]},
            metric_definitions={"gmv": "SUM(total)"},
        ),
    )
    compiler = SkillCompiler()
    result = compiler.compile(spec)
    entry = SkillRegistryEntry(
        skill_spec=spec,
        compiled_skill=result.compiled_skill,
        enabled=True,
    )
    return entry


class TestSkillRouter:
    def test_selects_matching_pattern(self):
        router = SkillRouter(min_match_score=0.1)
        entry = _make_compiled_entry(
            "retail", patterns=["(?i)\\brevenue\\b"]
        )
        results = router.select_skills("Show total revenue", [entry])
        assert len(results) == 1
        assert results[0].skill_name == "retail"
        assert results[0].match_score > 0

    def test_no_match_returns_empty(self):
        router = SkillRouter(min_match_score=0.1)
        entry = _make_compiled_entry(
            "retail", patterns=["(?i)\\brevenue\\b"]
        )
        results = router.select_skills("How is the weather?", [entry])
        assert len(results) == 0

    def test_keyword_matching(self):
        router = SkillRouter(min_match_score=0.1)
        entry = _make_compiled_entry(
            "retail",
            hints=["total revenue by month", "top selling products"],
        )
        results = router.select_skills("Show total revenue", [entry])
        assert len(results) >= 1

    def test_disabled_skills_excluded(self):
        router = SkillRouter(min_match_score=0.0)
        entry = _make_compiled_entry(
            "retail", patterns=["(?i)\\brevenue\\b"]
        )
        entry.enabled = False
        results = router.select_skills("revenue", [entry])
        assert len(results) == 0

    def test_uncompiled_skills_excluded(self):
        router = SkillRouter(min_match_score=0.0)
        spec = SkillSpec(
            name="uncompiled", provenance=SkillProvenance(author="test")
        )
        entry = SkillRegistryEntry(
            skill_spec=spec, compiled_skill=None, enabled=True,
        )
        results = router.select_skills("anything", [entry])
        assert len(results) == 0

    def test_merge_context(self):
        s1 = SelectedSkill(
            skill_id="1", skill_name="a", version="1.0", match_score=0.8,
            glossary_additions={"revenue": ["sales"]},
            policy_constraints={"required_filters": ["tenant_id = 1"]},
            rendering_defaults={"currency": "USD"},
        )
        s2 = SelectedSkill(
            skill_id="2", skill_name="b", version="1.0", match_score=0.6,
            glossary_additions={"revenue": ["turnover"]},
            policy_constraints={"required_filters": ["region = 'US'"]},
            rendering_defaults={"currency": "GBP"},
        )
        merged = SkillRouter.merge_skill_context([s1, s2])
        assert "sales" in merged["glossary"]["revenue"]
        assert "turnover" in merged["glossary"]["revenue"]
        assert len(merged["skill_ids"]) == 2
        # Rendering uses highest scoring
        assert merged["rendering"]["currency"] == "USD"

    def test_max_skills_limit(self):
        router = SkillRouter(min_match_score=0.0, max_skills=2)
        entries = [
            _make_compiled_entry(f"skill_{i}", patterns=[".*"])
            for i in range(5)
        ]
        results = router.select_skills("anything", entries)
        assert len(results) <= 2
