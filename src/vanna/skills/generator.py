"""
Skill Generator — creates proposed SkillSpec + eval draft from schema and intent.

PROPOSAL ONLY: generates draft skills that cannot be promoted beyond draft.
Uses LLM for generation but validates output with the compiler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .compiler import SkillCompiler
from .models import (
    EvalExpectation,
    EvalSuite,
    IntentTrigger,
    KnowledgeMapping,
    RenderingDefaults,
    SkillEnvironment,
    SkillPolicy,
    SkillProvenance,
    SkillSpec,
    SqlLimits,
    CompilationResult,
)


@dataclass
class RiskChecklistItem:
    """One item in the risk checklist."""

    category: str
    description: str
    severity: str  # low, medium, high


@dataclass
class GeneratorOutput:
    """Output from the skill generator."""

    skill_spec: SkillSpec
    eval_dataset: List[EvalExpectation]
    risk_checklist: List[RiskChecklistItem]
    compilation_result: Optional[CompilationResult] = None
    warnings: List[str] = field(default_factory=list)


class SkillGenerator:
    """Generates proposed SkillSpec + eval draft from schema and natural language.

    IMPORTANT CONSTRAINTS:
      - Output is proposal-only (draft environment)
      - Cannot auto-publish or promote beyond draft
      - Generated spec is validated by the compiler
    """

    def __init__(
        self,
        *,
        compiler: Optional[SkillCompiler] = None,
    ) -> None:
        self._compiler = compiler or SkillCompiler()

    async def generate(
        self,
        *,
        schema_catalog: Dict[str, Any],
        tenant_glossary: List[Dict[str, Any]],
        description: str,
        llm_service: Any = None,
        tenant_id: Optional[str] = None,
        author: str = "skill_generator",
    ) -> GeneratorOutput:
        """Generate a proposed skill spec + eval dataset.

        Args:
            schema_catalog: Database schema snapshot (tables, columns, types)
            tenant_glossary: Existing glossary entries for context
            description: Natural language description of desired capability
            llm_service: Optional LLM service for AI-assisted generation
            tenant_id: Target tenant
            author: Author attribution

        Returns:
            GeneratorOutput with proposed spec, eval draft, and risk checklist
        """
        warnings: List[str] = []

        if llm_service is not None:
            # Use LLM to generate spec from description + schema
            spec, evals, risks = await self._generate_with_llm(
                schema_catalog=schema_catalog,
                tenant_glossary=tenant_glossary,
                description=description,
                llm_service=llm_service,
                tenant_id=tenant_id,
                author=author,
            )
        else:
            # Template-based generation (no LLM)
            spec, evals, risks = self._generate_template(
                schema_catalog=schema_catalog,
                tenant_glossary=tenant_glossary,
                description=description,
                tenant_id=tenant_id,
                author=author,
            )
            warnings.append(
                "Generated from template (no LLM). "
                "Intents and eval questions are placeholders."
            )

        # Force draft environment — generator cannot create non-draft
        spec.environment = SkillEnvironment.DRAFT

        # Validate with compiler
        compilation = self._compiler.compile(spec)

        return GeneratorOutput(
            skill_spec=spec,
            eval_dataset=evals,
            risk_checklist=risks,
            compilation_result=compilation,
            warnings=warnings,
        )

    def _generate_template(
        self,
        *,
        schema_catalog: Dict[str, Any],
        tenant_glossary: List[Dict[str, Any]],
        description: str,
        tenant_id: Optional[str],
        author: str,
    ) -> tuple:
        """Template-based generation without LLM."""
        # Extract table names from schema for context
        tables = list(schema_catalog.get("tables", {}).keys())

        # Build skill name from description
        name = description[:50].strip().replace(" ", "_").lower()

        # Build glossary synonyms from existing tenant glossary
        synonyms: Dict[str, List[str]] = {}
        for entry in tenant_glossary:
            if "term" in entry and "synonyms" in entry:
                synonyms[entry["term"]] = entry["synonyms"]

        spec = SkillSpec(
            name=name,
            version="1.0.0",
            tenant_id=tenant_id,
            environment=SkillEnvironment.DRAFT,
            description=description,
            provenance=SkillProvenance(
                author=author,
                generator_metadata={
                    "method": "template",
                    "tables": tables,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            ),
            intents=IntentTrigger(
                patterns=[],
                embedding_hints=[description],
                tool_routing_hints=["run_sql"],
            ),
            knowledge=KnowledgeMapping(
                synonyms=synonyms,
            ),
            policies=SkillPolicy(
                sql_limits=SqlLimits(
                    read_only=True,
                    max_rows=1000,
                    require_limit=True,
                    forbid_ddl_dml=True,
                ),
                required_filters=[f"tenant_id = '{tenant_id}'"]
                if tenant_id
                else [],
            ),
            rendering=RenderingDefaults(),
            eval_suite=EvalSuite(
                inline_evals=self._generate_placeholder_evals(
                    description, tables
                ),
            ),
        )

        evals = list(spec.eval_suite.inline_evals)

        risks = self._generate_risk_checklist(spec, tables)

        return spec, evals, risks

    async def _generate_with_llm(
        self,
        *,
        schema_catalog: Dict[str, Any],
        tenant_glossary: List[Dict[str, Any]],
        description: str,
        llm_service: Any,
        tenant_id: Optional[str],
        author: str,
    ) -> tuple:
        """LLM-assisted generation. Falls back to template on failure."""
        # Build prompt
        prompt = self._build_generation_prompt(
            schema_catalog, tenant_glossary, description, tenant_id
        )

        try:
            # Use LLM to generate structured output
            response = await llm_service.generate(prompt)
            response_text = (
                response if isinstance(response, str) else str(response)
            )

            # Try to parse structured output
            spec = self._parse_llm_output(
                response_text, description, tenant_id, author
            )
            evals = list(spec.eval_suite.inline_evals)
            tables = list(schema_catalog.get("tables", {}).keys())
            risks = self._generate_risk_checklist(spec, tables)
            return spec, evals, risks

        except Exception:
            # Fallback to template
            return self._generate_template(
                schema_catalog=schema_catalog,
                tenant_glossary=tenant_glossary,
                description=description,
                tenant_id=tenant_id,
                author=author,
            )

    def _build_generation_prompt(
        self,
        schema_catalog: Dict[str, Any],
        tenant_glossary: List[Dict[str, Any]],
        description: str,
        tenant_id: Optional[str],
    ) -> str:
        tables_info = json.dumps(
            list(schema_catalog.get("tables", {}).keys()), indent=2
        )
        glossary_info = json.dumps(tenant_glossary[:20], indent=2)

        return f"""Generate a Vanna SkillSpec in JSON format for the following capability:

Description: {description}
Tenant: {tenant_id or 'global'}

Available tables: {tables_info}
Existing glossary: {glossary_info}

Output a JSON object with these fields:
- name: skill name
- intents: {{ patterns: [...], embedding_hints: [...] }}
- knowledge: {{ synonyms: {{term: [syns]}}, metric_definitions: {{name: sql}} }}
- eval_questions: [{{ question: "...", constraints: ["..."] }}]

IMPORTANT: The skill MUST use read-only SQL. Generate at least 10 eval questions."""

    def _parse_llm_output(
        self,
        response: str,
        description: str,
        tenant_id: Optional[str],
        author: str,
    ) -> SkillSpec:
        """Parse LLM output into a SkillSpec. Falls back to template on error."""
        # Try to extract JSON from the LLM response
        try:
            # Find JSON in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(response[start:end])
            else:
                raise ValueError("No JSON found in response")

            # Build SkillSpec from parsed data
            intents_data = data.get("intents", {})
            knowledge_data = data.get("knowledge", {})
            eval_questions = data.get("eval_questions", [])

            evals = [
                EvalExpectation(
                    question=q.get("question", ""),
                    constraints=q.get("constraints", []),
                )
                for q in eval_questions
            ]

            return SkillSpec(
                name=data.get("name", description[:50]),
                version="1.0.0",
                tenant_id=tenant_id,
                environment=SkillEnvironment.DRAFT,
                description=description,
                provenance=SkillProvenance(
                    author=author,
                    generator_metadata={"method": "llm"},
                ),
                intents=IntentTrigger(
                    patterns=intents_data.get("patterns", []),
                    embedding_hints=intents_data.get("embedding_hints", [description]),
                    tool_routing_hints=["run_sql"],
                ),
                knowledge=KnowledgeMapping(
                    synonyms=knowledge_data.get("synonyms", {}),
                    metric_definitions=knowledge_data.get("metric_definitions", {}),
                ),
                policies=SkillPolicy(
                    sql_limits=SqlLimits(read_only=True, forbid_ddl_dml=True),
                    required_filters=[f"tenant_id = '{tenant_id}'"]
                    if tenant_id
                    else [],
                ),
                eval_suite=EvalSuite(inline_evals=evals),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            raise ValueError("Failed to parse LLM output as valid SkillSpec")

    def _generate_placeholder_evals(
        self, description: str, tables: List[str]
    ) -> List[EvalExpectation]:
        """Generate placeholder eval questions from table names."""
        evals: List[EvalExpectation] = []
        templates = [
            ("How many records are in {table}?", ["result contains count", "returns numeric value"]),
            ("Show the top 10 rows from {table}", ["returns at most 10 rows", "uses LIMIT clause"]),
            ("What are the distinct values in {table}?", ["uses DISTINCT", "returns column values"]),
        ]
        for table in tables[:5]:
            for template, constraints in templates:
                evals.append(
                    EvalExpectation(
                        question=template.format(table=table),
                        constraints=constraints,
                        expected_tool="run_sql",
                    )
                )
        # Ensure at least 10
        while len(evals) < 10:
            evals.append(
                EvalExpectation(
                    question=f"Question about: {description}",
                    constraints=["returns valid result", "uses read-only SQL"],
                )
            )
        return evals

    def _generate_risk_checklist(
        self, spec: SkillSpec, tables: List[str]
    ) -> List[RiskChecklistItem]:
        """Generate risk checklist based on the skill spec."""
        risks: List[RiskChecklistItem] = []

        # Data access scope
        risks.append(
            RiskChecklistItem(
                category="data_access",
                description=f"Skill may access data from tables: {', '.join(tables[:10])}",
                severity="medium",
            )
        )

        # Policy completeness
        if not spec.policies.required_filters:
            risks.append(
                RiskChecklistItem(
                    category="tenant_isolation",
                    description="No required tenant filter. Data from all tenants may be accessible.",
                    severity="high",
                )
            )

        # Eval coverage
        eval_count = len(spec.eval_suite.inline_evals)
        if eval_count < 15:
            risks.append(
                RiskChecklistItem(
                    category="eval_coverage",
                    description=f"Only {eval_count} eval questions. Consider adding more for production use.",
                    severity="low",
                )
            )

        return risks
