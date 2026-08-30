"""Strict I/O contracts for every runtime agent.

Free-form model text is never consumed by downstream logic — only validated
structured output is. An agent that cannot produce a conforming object has
produced nothing, and the orchestrator records that rather than improvising.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aftermath.replay.intervention import InterventionKind
from aftermath.replay.repair import RepairKind


class Hypothesis(BaseModel):
    """A causal claim bound to a specific trace step."""

    model_config = ConfigDict(extra="forbid")

    suspected_step_id: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    # Advisory only. Ranking uses measured effect size (D-001); this is recorded
    # so a report can show how well the agent's certainty tracked the evidence.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    supporting_step_ids: list[str] = Field(default_factory=list)
    falsifiable_prediction: str = ""


class InvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypotheses: list[Hypothesis] = Field(default_factory=list)


class PlannedExperiment(BaseModel):
    """A hypothesis turned into something executable."""

    model_config = ConfigDict(extra="forbid")

    suspected_step_id: str = Field(min_length=1)
    intervention_kind: InterventionKind
    # Only meaningful for replace_tool_result; the planner may leave it unset and
    # let the orchestrator supply the value from a healthy run.
    use_healthy_value: bool = True
    rationale: str = ""


class PlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiments: list[PlannedExperiment] = Field(default_factory=list)


class RepairProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RepairKind
    rationale: str = ""


class RepairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[RepairProposal] = Field(default_factory=list)


class VerificationOutput(BaseModel):
    """The verifier reads measured results, not agent opinions."""

    model_config = ConfigDict(extra="forbid")

    evidence_sufficient: bool
    concerns: list[str] = Field(default_factory=list)
    residual_risk: str = ""
