"""The deterministic replay engine.

**What "replay" means here, precisely.** This engine does not step through a
recorded trace re-emitting recorded values — that would be playback, and playback
cannot answer a counterfactual, because after an intervention the run must be
free to diverge. Replay here is *deterministic re-execution*: the same scenario,
the same world seed, the same fault, and the same recorded model responses, run
again. Given those fixed inputs the agent reproduces its trace exactly; change
one thing and everything downstream may legitimately differ. That is the whole
point.

**No LLM calls happen in this package.** A provider may be handed in from
outside for model narration, but nothing here imports the LLM layer, and no model
is ever asked whether a run failed. Enforced by
`tests/arch/test_import_boundaries.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aftermath.companyagent.base import AgentRun
from aftermath.companyagent.scenarios import get_scenario
from aftermath.companyagent.simple import SimpleCustomerOpsAgent
from aftermath.companyagent.tools import ToolOutcome
from aftermath.companyagent.world import World, build_world
from aftermath.core.trace import OutcomeStatus, Trace
from aftermath.injection.injector import Injector, NullInjector
from aftermath.injection.spec import InjectionSpec
from aftermath.replay.intervention import (
    InterventionKind,
    InterventionSpec,
    ResolvedTarget,
    resolve_target,
)

SUPPRESSED_ERROR = "call suppressed by counterfactual intervention"


class CompositeInjector:
    """Applies the original fault, then any interventions on top of it.

    Order matters and is deliberate: the fault is applied first, then the
    intervention overrides it. A counterfactual asks "what if this step had gone
    differently *than it actually did*", so it must act on the faulted run, not
    on a hypothetical clean one.
    """

    def __init__(
        self,
        fault: Injector | NullInjector,
        interventions: dict[tuple[str, int], InterventionSpec],
    ) -> None:
        self._fault = fault
        self._interventions = interventions
        self._seen: dict[str, int] = {}
        self.applied: list[str] = []

    @property
    def fired(self) -> bool:
        return bool(getattr(self._fault, "fired", False))

    def ground_truth(self):
        return self._fault.ground_truth() if self.fired else None

    def _match(self, tool: str, *, advance: bool) -> InterventionSpec | None:
        occurrence = self._seen.get(tool, 0) + (1 if advance else 0)
        if advance:
            self._seen[tool] = occurrence
        return self._interventions.get((tool, occurrence))

    # ---- hooks ---------------------------------------------------------------

    def prepare_world(self, world: World) -> World:
        # A suppression intervention that targets the fault removes it entirely,
        # including a world-layer perturbation that happens before the run.
        if any(
            spec.kind is InterventionKind.SUPPRESS_INJECTED_FAULT
            for spec in self._interventions.values()
        ):
            return world
        return self._fault.prepare_world(world)

    def override_call(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome | None:
        spec = self._match(tool, advance=True)
        if spec is not None and spec.kind is InterventionKind.SKIP_TOOL_CALL:
            self.applied.append(spec.step_id)
            return ToolOutcome(error=SUPPRESSED_ERROR)
        return self._fault.override_call(tool, arguments)

    def transform_outcome(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome, world: World
    ) -> ToolOutcome:
        spec = self._match(tool, advance=False)

        if spec is not None and spec.kind is InterventionKind.SUPPRESS_INJECTED_FAULT:
            # Skip the fault entirely for this call: the tool's natural result stands.
            self.applied.append(spec.step_id)
            return outcome

        faulted = self._fault.transform_outcome(tool, arguments, outcome, world)

        if spec is not None and spec.kind is InterventionKind.REPLACE_TOOL_RESULT:
            self.applied.append(spec.step_id)
            return ToolOutcome(result=spec.replacement, mutations=faulted.mutations)
        return faulted

    def extra_calls(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome
    ) -> list[tuple[str, dict[str, Any]]]:
        return self._fault.extra_calls(tool, arguments, outcome)

    def note_step(self, *, call_step: str, result_step: str) -> None:
        self._fault.note_step(call_step=call_step, result_step=result_step)


@dataclass(frozen=True)
class ReplayRequest:
    """Everything needed to re-execute a run, plus what to change."""

    scenario_id: str
    seed: int
    injection: InjectionSpec | None = None
    interventions: tuple[InterventionSpec, ...] = ()
    # Optional model provider for narration, supplied by the caller. Typed loosely
    # on purpose: this package must not import the LLM layer.
    provider: Any = None


@dataclass(frozen=True)
class ReplayResult:
    """The outcome of one replay."""

    trace: Trace
    world: World
    applied_interventions: tuple[str, ...] = ()
    unmatched_interventions: tuple[str, ...] = field(default=())

    @property
    def failed(self) -> bool:
        """Decided by the scenario oracle in Python — never by a model."""
        return self.trace.outcome.status is OutcomeStatus.FAIL

    @property
    def content_hash(self) -> str:
        return self.trace.content_hash()


class ReplayEngine:
    """Re-executes runs deterministically, with or without interventions."""

    def replay(self, request: ReplayRequest) -> ReplayResult:
        """Execute one replay.

        Raises:
            TargetNotFoundError: if an intervention names a step that does not
                exist in the baseline run.
        """
        targets = self._resolve(request)
        fault: Injector | NullInjector = (
            Injector(request.injection) if request.injection else NullInjector()
        )
        composite = CompositeInjector(
            fault, {(t.tool, t.occurrence): spec for t, spec in targets}
        )
        agent = SimpleCustomerOpsAgent(
            request.provider,
            narrate=request.provider is not None,
            injector=composite,
        )
        run: AgentRun = agent.run(get_scenario(request.scenario_id), build_world(request.seed))

        applied = tuple(composite.applied)
        requested = tuple(spec.step_id for _, spec in targets)
        return ReplayResult(
            trace=run.trace,
            world=run.world,
            applied_interventions=applied,
            unmatched_interventions=tuple(s for s in requested if s not in applied),
        )

    def baseline(self, scenario_id: str, seed: int, injection: InjectionSpec | None,
                 provider: Any = None) -> ReplayResult:
        """Replay with the fault but no intervention — the comparison point."""
        return self.replay(
            ReplayRequest(
                scenario_id=scenario_id, seed=seed, injection=injection, provider=provider
            )
        )

    def _resolve(
        self, request: ReplayRequest
    ) -> list[tuple[ResolvedTarget, InterventionSpec]]:
        """Map each intervention's step id onto the call it identifies.

        Resolution uses an uninterfered baseline run, so a step id always means
        the same thing regardless of which interventions are being tested.
        """
        if not request.interventions:
            return []
        reference = self.replay(
            ReplayRequest(
                scenario_id=request.scenario_id,
                seed=request.seed,
                injection=request.injection,
                provider=request.provider,
            )
        ).trace
        return [(resolve_target(reference, spec.step_id), spec) for spec in request.interventions]
