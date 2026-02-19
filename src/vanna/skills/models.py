"""
Pydantic models for the Skill Fabric.

Defines SkillSpec (the declarative skill definition), CompiledSkill (the
deterministic runtime artifact produced by the compiler), and supporting
types for the registry, audit log, and compilation results.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SkillEnvironment(str, Enum):
    """Lifecycle states for a skill."""

    DRAFT = "draft"
    TESTED = "tested"
    APPROVED = "approved"
    DEFAULT = "default"


# ---------------------------------------------------------------------------
# SkillSpec sub-models
# ---------------------------------------------------------------------------


class SkillProvenance(BaseModel):
    """Who/what created this skill and when."""

    author: str = Field(description="Human or system that authored the spec")
    generator_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadata from the generator (model, prompt hash, etc.)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class IntentTrigger(BaseModel):
    """Defines when a skill should activate."""

    patterns: List[str] = Field(
        default_factory=list,
        description="Regex or keyword patterns that match user questions",
    )
    embedding_hints: List[str] = Field(
        default_factory=list,
        description="Phrases for semantic similarity matching",
    )
    tool_routing_hints: List[str] = Field(
        default_factory=list,
        description="Hints to the router about which tools are relevant",
    )


class KnowledgeMapping(BaseModel):
    """Glossary additions and semantic mappings contributed by the skill."""

    synonyms: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Term → list of synonyms to add",
    )
    metric_definitions: Dict[str, str] = Field(
        default_factory=dict,
        description="Metric name → SQL / semantic definition",
    )
    semantic_mappings: Dict[str, str] = Field(
        default_factory=dict,
        description="Concept → semantic layer reference (optional)",
    )


class SqlLimits(BaseModel):
    """Safety limits for SQL generated under this skill."""

    read_only: bool = Field(
        default=True, description="Forbid INSERT/UPDATE/DELETE/DDL"
    )
    max_rows: Optional[int] = Field(
        default=1000, description="Maximum rows returned"
    )
    max_runtime_seconds: Optional[int] = Field(
        default=30, description="Maximum query runtime"
    )
    require_limit: bool = Field(
        default=True, description="Require LIMIT clause"
    )
    forbid_ddl_dml: bool = Field(
        default=True, description="Forbid DDL and DML statements"
    )


class SkillPolicy(BaseModel):
    """Security and governance policies for a skill."""

    tool_allowlist: List[str] = Field(
        default_factory=list,
        description="Tools this skill is allowed to use (empty = use defaults)",
    )
    tool_denylist: List[str] = Field(
        default_factory=list,
        description="Tools this skill must NOT use",
    )
    required_filters: List[str] = Field(
        default_factory=list,
        description="SQL WHERE predicates that must be present (e.g. tenant_id = ?)",
    )
    row_redaction_rules: List[str] = Field(
        default_factory=list,
        description="Column-level redaction rules (e.g. mask SSN columns)",
    )
    column_redaction_rules: List[str] = Field(
        default_factory=list,
        description="Column redaction rules",
    )
    sql_limits: SqlLimits = Field(default_factory=SqlLimits)


class RenderingDefaults(BaseModel):
    """Presentation defaults contributed by the skill."""

    currency: Optional[str] = Field(default=None)
    locale: Optional[str] = Field(default=None)
    date_format: Optional[str] = Field(default=None)
    preferred_output_layout: Optional[str] = Field(
        default=None, description="table, chart, card, etc."
    )


class EvalExpectation(BaseModel):
    """A single evaluation question with constraint-based expectations."""

    question: str = Field(description="Natural-language question")
    constraints: List[str] = Field(
        description="Constraint descriptions (not golden SQL)",
    )
    expected_tool: Optional[str] = Field(
        default=None, description="Expected tool to be invoked"
    )
    tags: List[str] = Field(default_factory=list)


class EvalSuite(BaseModel):
    """Evaluation dataset and thresholds."""

    eval_data_path: Optional[str] = Field(
        default=None,
        description="File path to external eval dataset (YAML/JSON)",
    )
    inline_evals: List[EvalExpectation] = Field(
        default_factory=list,
        description="Inline eval expectations",
    )
    pass_rate_threshold: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Minimum pass rate"
    )
    min_score: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Minimum average score"
    )


# ---------------------------------------------------------------------------
# SkillSpec (top-level)
# ---------------------------------------------------------------------------


class SkillSpec(BaseModel):
    """Declarative, versioned skill definition.

    Supports ANY domain. Domain-specific logic lives in pack artifacts,
    not in the framework.
    """

    name: str = Field(description="Human-readable skill name")
    version: str = Field(default="1.0.0", description="Semantic version")
    tenant_id: Optional[str] = Field(
        default=None, description="Tenant scope (None = global template)"
    )
    environment: SkillEnvironment = Field(default=SkillEnvironment.DRAFT)
    description: Optional[str] = Field(
        default=None, description="What this skill does"
    )

    provenance: SkillProvenance = Field(default_factory=SkillProvenance)
    intents: IntentTrigger = Field(default_factory=IntentTrigger)
    knowledge: KnowledgeMapping = Field(default_factory=KnowledgeMapping)
    policies: SkillPolicy = Field(default_factory=SkillPolicy)
    rendering: RenderingDefaults = Field(default_factory=RenderingDefaults)
    eval_suite: EvalSuite = Field(default_factory=EvalSuite)


# ---------------------------------------------------------------------------
# CompiledSkill
# ---------------------------------------------------------------------------


class CompiledSkill(BaseModel):
    """Deterministic runtime artifact produced by the Skill Compiler.

    Used by the router/planner to apply skill context without re-parsing the spec.
    """

    skill_spec_hash: str = Field(
        description="SHA-256 of the canonical SkillSpec JSON"
    )
    compiled_at: datetime = Field(default_factory=datetime.utcnow)
    version: str = Field(description="SkillSpec version at compilation time")

    # Pre-computed indices
    intent_patterns: List[str] = Field(default_factory=list)
    embedding_hints: List[str] = Field(default_factory=list)
    tool_routing_hints: List[str] = Field(default_factory=list)

    # Flattened policy constraints for fast enforcement
    policy_constraints: Dict[str, Any] = Field(default_factory=dict)

    # Glossary additions
    glossary_additions: Dict[str, List[str]] = Field(default_factory=dict)

    # Rendering config
    rendering_config: Dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def compute_spec_hash(spec: SkillSpec) -> str:
        """Deterministic hash of the spec for cache invalidation."""
        canonical = spec.model_dump_json(exclude_none=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class CompilationResult(BaseModel):
    """Outcome of compiling a SkillSpec."""

    success: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    compiled_skill: Optional[CompiledSkill] = None


# ---------------------------------------------------------------------------
# Registry supporting models
# ---------------------------------------------------------------------------


class SkillAuditEntry(BaseModel):
    """Single audit log entry for a skill state transition."""

    action: str = Field(description="e.g. created, promoted, disabled, deleted")
    actor: str = Field(description="User who performed the action")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    from_env: Optional[SkillEnvironment] = None
    to_env: Optional[SkillEnvironment] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class SkillRegistryEntry(BaseModel):
    """A registered skill in the registry with lifecycle metadata."""

    skill_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this registry entry",
    )
    skill_spec: SkillSpec
    compiled_skill: Optional[CompiledSkill] = None
    environment: SkillEnvironment = Field(default=SkillEnvironment.DRAFT)
    enabled: bool = Field(default=True)
    tenant_id: Optional[str] = None
    created_by: str = Field(default="system")
    audit_log: List[SkillAuditEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
