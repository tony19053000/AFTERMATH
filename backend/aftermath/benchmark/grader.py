"""Deterministic grading against injector ground truth.

The same grader scores AFTERMATH and the baseline. If they were graded
differently the comparison would be meaningless, so there is exactly one
implementation and both systems are routed through it.

**The near-miss problem.** With causal chains, an answer of `s0009` when the true
cause is `s0007` is not a random error — it names a step that genuinely carries
the fault forward, and correcting it also prevents the failure. Scoring that
identically to a wild guess would flatter whichever system happens to answer
upstream. So the grader computes the **causal set** — every step whose correction
prevents the failure, measured by replay, not assumed — and reports `NEAR_MISS`
separately.

`NEAR_MISS` is **never** counted as a success in the primary metric. It is
reported alongside so the comparison is informative rather than generous.

No LLM calls in this module.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.trace import StepType
from aftermath.injection.incidents import IncidentDefinition, load_incidents
from aftermath.injection.runner import run_clean, run_incident
from aftermath.replay.experiment import ExperimentRunner
from aftermath.replay.intervention import (
    InterventionKind,
    InterventionSpec,
    addressable_steps,
)

CAUSAL_EFFECT_THRESHOLD = 0.5
CAUSAL_SET_TRIALS = 3


class Verdict(StrEnum):
    EXACT = "exact"
    NEAR_MISS = "near_miss"
    WRONG = "wrong"
    NO_ANSWER = "no_answer"


class GradedAnswer(BaseModel):
    """One system's answer on one incident, scored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: str
    system: str
    answered_step: str | None
    true_causal_step: str
    causal_set: tuple[str, ...] = ()
    verdict: Verdict

    @property
    def correct(self) -> bool:
        """Only an exact match counts. A near miss is reported, never credited."""
        return self.verdict is Verdict.EXACT


@lru_cache(maxsize=64)
def causal_set(incident_id: str) -> tuple[str, ...]:
    """Every step whose correction prevents the failure, measured by replay.

    Cached because it is expensive and fully deterministic: the same incident
    always yields the same set.
    """
    incident = load_incidents()[incident_id]
    trace = run_incident(incident).run.trace
    healthy = run_clean(incident.scenario_id).trace
    natural = {
        s.tool: s.result
        for s in healthy.steps
        if s.type is StepType.TOOL_RESULT and s.result is not None
    }
    runner = ExperimentRunner()

    members: list[str] = []
    candidates = list(addressable_steps(trace)) + [
        s.step_id
        for s in trace.steps
        if s.type is StepType.TOOL_CALL and _is_repeat(trace, s.step_id)
    ]
    for step_id in sorted(set(candidates)):
        step = trace.step(step_id)
        if step.type is StepType.TOOL_CALL:
            spec = InterventionSpec(kind=InterventionKind.SKIP_TOOL_CALL, step_id=step_id)
        else:
            replacement = natural.get(step.tool)
            if replacement is None:
                continue
            spec = InterventionSpec(
                kind=InterventionKind.REPLACE_TOOL_RESULT,
                step_id=step_id,
                replacement=replacement,
            )
        result = runner.run(
            scenario_id=incident.scenario_id,
            seed=incident.replay_configuration.seed,
            injection=incident.injected_failure,
            intervention=spec,
            trials=CAUSAL_SET_TRIALS,
        )
        if result.effect_size >= CAUSAL_EFFECT_THRESHOLD:
            members.append(step_id)
    return tuple(members)


def _is_repeat(trace, step_id: str) -> bool:
    target = trace.step(step_id)
    for step in trace.steps:
        if step.step_id == step_id:
            return False
        if (
            step.type is StepType.TOOL_CALL
            and step.tool == target.tool
            and step.arguments == target.arguments
        ):
            return True
    return False


def grade(
    incident: IncidentDefinition,
    system: str,
    answered_step: str | None,
) -> GradedAnswer:
    """Score one answer. Identical logic for every system under test."""
    truth = run_incident(incident).run.trace.injection.true_causal_step
    members = causal_set(incident.incident_id)

    if answered_step is None:
        verdict = Verdict.NO_ANSWER
    elif answered_step == truth:
        verdict = Verdict.EXACT
    elif answered_step in members:
        verdict = Verdict.NEAR_MISS
    else:
        verdict = Verdict.WRONG

    return GradedAnswer(
        incident_id=incident.incident_id,
        system=system,
        answered_step=answered_step,
        true_causal_step=truth,
        causal_set=members,
        verdict=verdict,
    )
