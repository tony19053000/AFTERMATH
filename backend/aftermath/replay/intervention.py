"""Counterfactual interventions.

An intervention asks a falsifiable question: *if this step had gone differently,
would the run still have failed?* The replay engine answers it by measurement.

Interventions address steps by `step_id`. Because step ids are ordinal and the
agent is deterministic under a fixed seed, a step id resolves to the same
`(tool, occurrence)` on every replay — which is what makes an intervention
reproducible rather than "whichever call happened to match".

Nothing here imports the LLM layer. An intervention is a mechanical edit to a
run; deciding *which* interventions are worth trying is the counterfactual
planner's job in P5, and deciding whether one worked is the scorer's.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.trace import StepType, Trace


class InterventionKind(StrEnum):
    """What to do differently at the targeted step."""

    # Substitute a specific value for a tool's result.
    REPLACE_TOOL_RESULT = "replace_tool_result"
    # Prevent a call from executing at all — the only way to undo an action.
    SKIP_TOOL_CALL = "skip_tool_call"
    # Undo whatever the fault injector did, without needing to know what it was.
    SUPPRESS_INJECTED_FAULT = "suppress_injected_fault"


class InterventionSpec(BaseModel):
    """One surgical change to a run.

    Deliberately single-target: an intervention that alters several steps at once
    cannot localize a cause, because a change in outcome could not be attributed
    to any one of them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: InterventionKind
    step_id: str = Field(min_length=1)
    replacement: dict[str, Any] | None = None
    # Free-text note from whoever proposed it. Never used in scoring.
    rationale: str | None = None

    def model_post_init(self, _context: object) -> None:
        if self.kind is InterventionKind.REPLACE_TOOL_RESULT and self.replacement is None:
            raise ValueError("replace_tool_result requires a `replacement` value")


class TargetNotFoundError(KeyError):
    """The intervention names a step that is not an addressable tool call."""


class ResolvedTarget(BaseModel):
    """A step id resolved to the call it identifies, so replay can find it again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    tool: str
    # 1-based index among calls to the same tool within the run.
    occurrence: int


def resolve_target(trace: Trace, step_id: str) -> ResolvedTarget:
    """Resolve ``step_id`` to the ``(tool, occurrence)`` it names.

    Accepts either the ``tool_call`` step or its matching ``tool_result`` step,
    since an investigator may reasonably point at either.

    Raises:
        TargetNotFoundError: if the step is absent or is not a tool step.
    """
    counts: dict[str, int] = {}
    call_index: dict[str, tuple[str, int]] = {}

    for step in trace.steps:
        if step.type is StepType.TOOL_CALL:
            counts[step.tool] = counts.get(step.tool, 0) + 1
            call_index[step.call_id] = (step.tool, counts[step.tool])
            if step.step_id == step_id:
                return ResolvedTarget(step_id=step_id, tool=step.tool, occurrence=counts[step.tool])
        elif step.type is StepType.TOOL_RESULT and step.step_id == step_id:
            tool, occurrence = call_index[step.call_id]
            return ResolvedTarget(step_id=step_id, tool=tool, occurrence=occurrence)

    raise TargetNotFoundError(
        f"step {step_id!r} is not an addressable tool call in trace {trace.trace_id!r}"
    )


def addressable_steps(trace: Trace) -> tuple[str, ...]:
    """Every ``tool_result`` step id an intervention could target.

    Used by the counterfactual planner (P5) to enumerate candidate targets, and
    by the negative controls to pick steps that are not the suspected cause.
    """
    return tuple(s.step_id for s in trace.steps if s.type is StepType.TOOL_RESULT)
