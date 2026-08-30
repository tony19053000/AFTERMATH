"""Regression cases: an incident, made permanently unable to return.

A case captures everything needed to re-stage a failure — scenario, seed,
injection, and the oracle that judged it — plus the repair proven to prevent it
and the evidence that proved it.

A case is only meaningful if it can **fail**. `verify_case_controls` asserts both
directions: it must fail against the unrepaired agent (otherwise it detects
nothing) and pass against the repaired one (otherwise the repair is not real).
A case that passes both ways is a green light that means nothing, and this module
refuses to store one.

No LLM calls here. Whether a case passes is decided by the scenario oracle.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.hashing import content_hash
from aftermath.core.trace import Severity
from aftermath.injection.incidents import IncidentDefinition
from aftermath.injection.spec import InjectionSpec
from aftermath.replay.repair import RepairSpec


class RegressionCase(BaseModel):
    """One permanently-retained failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    seed: int
    injection: InjectionSpec
    failing_oracle: str = Field(min_length=1)
    expected_safe_behavior: str = Field(min_length=1)
    severity: Severity = Severity.HIGH

    # What was proven, and what proved it.
    root_cause_step: str = Field(min_length=1)
    verified_repair: RepairSpec
    evidence_effect_size: float = Field(ge=0.0, le=1.0)
    evidence_artifact_hash: str = Field(min_length=1)
    trials: int = Field(default=5, gt=0)

    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class CaseControlsFailed(ValueError):
    """A case that cannot detect its own bug, or whose repair does not work."""


def build_case(
    incident: IncidentDefinition,
    *,
    root_cause_step: str,
    verified_repair: RepairSpec,
    evidence_effect_size: float,
    evidence_artifact_hash: str,
    trials: int = 5,
) -> RegressionCase:
    """Assemble a case from an incident and a repair that was measured to work.

    Takes primitives rather than a forensic report: `immunity/` and `forensics/`
    are siblings, and the vault must not depend on how a diagnosis was reached —
    only on what was proven. A case built from a hand-run experiment and one
    built by the agent pipeline are the same object.
    """
    return RegressionCase(
        case_id=f"RC-{incident.incident_id}",
        incident_id=incident.incident_id,
        scenario_id=incident.scenario_id,
        seed=incident.replay_configuration.seed,
        injection=incident.injected_failure,
        failing_oracle=incident.failing_oracle,
        expected_safe_behavior=incident.expected_safe_behavior,
        severity=incident.severity,
        root_cause_step=root_cause_step,
        verified_repair=verified_repair,
        evidence_effect_size=evidence_effect_size,
        evidence_artifact_hash=evidence_artifact_hash,
        trials=trials,
    )
