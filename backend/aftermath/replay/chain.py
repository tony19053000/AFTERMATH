"""Separating a cause from its consequences, by measurement.

P4 left a debt (D-016): when a fault and its downstream effects both prevent the
failure when corrected, they tie at maximum effect, and `localize()` broke the
tie by picking the earliest step — a heuristic, not evidence.

This module replaces that heuristic with an experiment. If correcting step A
*also* normalizes the value at step B, then B's wrongness was caused by A, and A
is upstream. That is a measurable dominance relation, not an ordering assumption.

    correct s0007 (stale policy)  ->  s0009's refund calculation becomes correct
    correct s0009 (refund calc)   ->  s0007 still returns the stale policy

So s0007 dominates s0009, and s0007 is the root cause. Deterministic Python
throughout: no model is consulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aftermath.core.trace import StepType, Trace
from aftermath.injection.spec import InjectionSpec
from aftermath.replay.engine import ReplayEngine, ReplayRequest
from aftermath.replay.intervention import InterventionSpec, resolve_target


@dataclass(frozen=True)
class DominanceEdge:
    """Evidence that correcting ``upstream`` also fixes ``downstream``."""

    upstream: str
    downstream: str
    normalized: bool


def _result_at(trace: Trace, tool: str, occurrence: int) -> Any:
    """The result of the nth call to ``tool``, matched positionally.

    Step ids shift once an intervention changes control flow, so downstream
    values are matched by (tool, occurrence) rather than by id.
    """
    seen = 0
    for step in trace.steps:
        if step.type is StepType.TOOL_RESULT and step.tool == tool:
            seen += 1
            if seen == occurrence:
                return step.result
    return None


def normalizes_downstream(
    engine: ReplayEngine,
    *,
    scenario_id: str,
    seed: int,
    injection: InjectionSpec | None,
    baseline_trace: Trace,
    healthy_trace: Trace,
    upstream: InterventionSpec,
    downstream_step_id: str,
) -> bool:
    """Does intervening at ``upstream`` make ``downstream_step_id`` correct on its own?

    True means the downstream step was merely carrying the upstream fault forward.
    """
    target = resolve_target(baseline_trace, downstream_step_id)
    healthy_value = _result_at(healthy_trace, target.tool, target.occurrence)
    if healthy_value is None:
        return False

    intervened = engine.replay(
        ReplayRequest(
            scenario_id=scenario_id,
            seed=seed,
            injection=injection,
            interventions=(upstream,),
        )
    ).trace
    return _result_at(intervened, target.tool, target.occurrence) == healthy_value


def refine_to_root_cause(
    engine: ReplayEngine,
    *,
    scenario_id: str,
    seed: int,
    injection: InjectionSpec | None,
    baseline_trace: Trace,
    healthy_trace: Trace,
    tied: list[tuple[str, InterventionSpec]],
) -> tuple[str | None, list[DominanceEdge]]:
    """Reduce a set of tied steps to the one that dominates the rest.

    Returns the root cause and the dominance evidence supporting it. If no step
    dominates all others, returns ``None``: an ambiguous chain is a real result,
    and picking a winner anyway would reintroduce the heuristic this replaces.
    """
    if not tied:
        return None, []
    if len(tied) == 1:
        return tied[0][0], []

    edges: list[DominanceEdge] = []
    for step_id, spec in tied:
        others = [other for other, _ in tied if other != step_id]
        dominates_all = True
        for other in others:
            normalized = normalizes_downstream(
                engine,
                scenario_id=scenario_id,
                seed=seed,
                injection=injection,
                baseline_trace=baseline_trace,
                healthy_trace=healthy_trace,
                upstream=spec,
                downstream_step_id=other,
            )
            edges.append(DominanceEdge(upstream=step_id, downstream=other, normalized=normalized))
            dominates_all = dominates_all and normalized
        if dominates_all:
            return step_id, edges
    return None, edges
