"""Tests for the Skill Generator."""

import pytest
import asyncio
from vanna.skills.generator import SkillGenerator, GeneratorOutput
from vanna.skills.models import SkillEnvironment


class TestSkillGenerator:
    def test_template_generation(self):
        async def run():
            gen = SkillGenerator()
            output = await gen.generate(
                schema_catalog={"tables": {"orders": {}, "products": {}, "customers": {}}},
                tenant_glossary=[
                    {"term": "GMV", "synonyms": ["gross merch value"]},
                ],
                description="Retail analytics for orders and products",
                tenant_id="acme",
            )
            assert isinstance(output, GeneratorOutput)
            assert output.skill_spec.environment == SkillEnvironment.DRAFT
            assert output.skill_spec.name  # Non-empty
            return output

        output = asyncio.run(run())

        # Check eval dataset has >= 10 questions
        assert len(output.eval_dataset) >= 10

        # Check risk checklist is non-empty
        assert len(output.risk_checklist) > 0

    def test_output_is_valid_skillspec(self):
        async def run():
            gen = SkillGenerator()
            output = await gen.generate(
                schema_catalog={"tables": {"orders": {}}},
                tenant_glossary=[],
                description="Order analytics",
            )
            # Should be a valid SkillSpec (Pydantic will validate)
            spec = output.skill_spec
            assert spec.name
            assert spec.version == "1.0.0"
            # Default policies should be safe
            assert spec.policies.sql_limits.read_only is True

        asyncio.run(run())

    def test_forced_draft_environment(self):
        async def run():
            gen = SkillGenerator()
            output = await gen.generate(
                schema_catalog={"tables": {}},
                tenant_glossary=[],
                description="test",
            )
            # Generator MUST force draft
            assert output.skill_spec.environment == SkillEnvironment.DRAFT

        asyncio.run(run())

    def test_compilation_result_included(self):
        async def run():
            gen = SkillGenerator()
            output = await gen.generate(
                schema_catalog={"tables": {"t": {}}},
                tenant_glossary=[],
                description="test skill",
                tenant_id="acme",
            )
            assert output.compilation_result is not None
            assert output.compilation_result.success is True

        asyncio.run(run())

    def test_includes_tenant_filter_when_given(self):
        async def run():
            gen = SkillGenerator()
            output = await gen.generate(
                schema_catalog={"tables": {}},
                tenant_glossary=[],
                description="test",
                tenant_id="acme",
            )
            filters = output.skill_spec.policies.required_filters
            assert any("acme" in f for f in filters)

        asyncio.run(run())
