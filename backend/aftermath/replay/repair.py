"""Repair guards and their evaluation.

A repair is a **parameterized guardrail selected from this library**, not code
written by a model. The repair agent chooses a kind and its parameters; this
module applies it and measures the result. That keeps the agent in the role of
proposer and Python in the role of judge (`CLAUDE.md` §2), and it means a repair
is executable and testable rather than a paragraph of advice.

Two numbers decide a repair, and both are required:

* **prevention rate** — how often the guard stops the incident,
* **false-block rate** — how often it breaks a normal case.

A guard that prevents everything by blocking everything scores 1.0 and 1.0, and
the false-block measurement is the only thing that catches it. Reporting
prevention alone would make such a repair look perfect.

No LLM calls in this module.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.companyagent.tools import ToolOutcome
from aftermath.companyagent.world import World
from aftermath.core.trace import OutcomeStatus
from aftermath.injection.injector import Injector, NullInjector
from aftermath.injection.spec import InjectionSpec
from aftermath.replay.engine import ReplayEngine, ReplayRequest

SUPPRESSED_BY_GUARD = "suppressed by repair guard: refund already issued for this order"


class RepairKind(StrEnum):
    """The guardrails a repair agent may select from."""

    IDEMPOTENT_REFUND = "idempotent_refund"
    VALIDATE_POLICY_FRESHNESS = "validate_policy_freshness"
    VALIDATE_POLICY_RESOLVES = "validate_policy_resolves"
    REDERIVE_APPROVAL = "rederive_approval"
    # Deliberately included so the tournament has a plausible-looking bad option:
    # it prevents everything by refusing every refund.
    BLOCK_ALL_REFUNDS = "block_all_refunds"


class RepairSpec(BaseModel):
    """One proposed guardrail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RepairKind
    rationale: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class RepairGuard:
    """Applies a repair on top of whatever the run would otherwise have done.

    Implements the same hook surface as the fault injector, so a guard composes
    with a fault without either knowing about the other.
    """

    def __init__(self, spec: RepairSpec, fault: Injector | NullInjector | None = None) -> None:
        self.spec = spec
        self._fault = fault or NullInjector()
        self.triggered = 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RepairGuard({self.spec.kind.value})"

    @property
    def fired(self) -> bool:
        return bool(getattr(self._fault, "fired", False))

    def ground_truth(self):
        return self._fault.ground_truth() if self.fired else None

    def prepare_world(self, world: World) -> World:
        return self._fault.prepare_world(world)

    def note_step(self, *, call_step: str, result_step: str) -> None:
        self._fault.note_step(call_step=call_step, result_step=result_step)

    def extra_calls(self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome):
        return self._fault.extra_calls(tool, arguments, outcome)

    def override_call(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome | None:
        if self.spec.kind is RepairKind.BLOCK_ALL_REFUNDS and tool == "issue_simulated_refund":
            self.triggered += 1
            return ToolOutcome(error="refunds disabled by guard")
        return self._fault.override_call(tool, arguments)

    def guard_before_call(self, tool: str, arguments: dict[str, Any], world: World):
        """Stateful pre-checks that need to read the world."""
        if self.spec.kind is RepairKind.IDEMPOTENT_REFUND and tool == "issue_simulated_refund":
            order_id = arguments.get("order_id")
            if world.total_refunded(order_id) > 0:
                self.triggered += 1
                return ToolOutcome(error=SUPPRESSED_BY_GUARD)
        return None

    def transform_outcome(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome, world: World
    ) -> ToolOutcome:
        faulted = self._fault.transform_outcome(tool, arguments, outcome, world)
        if faulted.failed or not faulted.result:
            return faulted

        match self.spec.kind:
            case RepairKind.VALIDATE_POLICY_FRESHNESS if tool == "get_policy":
                effective = world.effective_policy(arguments.get("policy_id", "refund"))
                if faulted.result.get("version") != effective.version:
                    self.triggered += 1
                    return ToolOutcome(result=effective.model_dump(mode="json"))

            case RepairKind.VALIDATE_POLICY_RESOLVES if tool == "get_policy":
                version = faulted.result.get("version")
                try:
                    world.policy_version(arguments.get("policy_id", "refund"), version)
                except KeyError:
                    self.triggered += 1
                    return ToolOutcome(
                        result=world.effective_policy(
                            arguments.get("policy_id", "refund")
                        ).model_dump(mode="json")
                    )

            case RepairKind.REDERIVE_APPROVAL if tool == "calculate_refund":
                # Never trust an upstream flag for a safety decision: recompute it.
                version = faulted.result.get("policy_version")
                try:
                    policy = world.policy_version("refund", version)
                except KeyError:
                    return faulted
                required = faulted.result.get("amount_cents", 0) > policy.auto_refund_limit_cents
                if required != faulted.result.get("requires_approval"):
                    self.triggered += 1
                    return ToolOutcome(
                        result={**faulted.result, "requires_approval": required},
                        mutations=faulted.mutations,
                    )
        return faulted


class GuardChain:
    """Several guards applied in sequence, over one fault.

    A released agent accumulates guardrails: an immunity suite must exercise all
    of them together, because a repair that works alone may be defeated by a
    later one, and only running them combined would reveal that.

    Each guard sees the output of the previous, so ordering is preserved and
    stated rather than incidental.
    """

    def __init__(self, specs: tuple[RepairSpec, ...], fault: Injector | NullInjector | None = None):
        self.specs = specs
        self._fault = fault or NullInjector()
        # Only the first guard carries the fault; the rest layer on top of it.
        self._guards = [RepairGuard(spec) for spec in specs]

    @property
    def triggered(self) -> int:
        return sum(g.triggered for g in self._guards)

    @property
    def fired(self) -> bool:
        return bool(getattr(self._fault, "fired", False))

    def ground_truth(self):
        return self._fault.ground_truth() if self.fired else None

    def prepare_world(self, world: World) -> World:
        return self._fault.prepare_world(world)

    def note_step(self, *, call_step: str, result_step: str) -> None:
        self._fault.note_step(call_step=call_step, result_step=result_step)

    def extra_calls(self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome):
        return self._fault.extra_calls(tool, arguments, outcome)

    def override_call(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome | None:
        for guard in self._guards:
            overridden = guard.override_call(tool, arguments)
            if overridden is not None:
                return overridden
        return self._fault.override_call(tool, arguments)

    def guard_before_call(self, tool: str, arguments: dict[str, Any], world: World):
        for guard in self._guards:
            guarded = guard.guard_before_call(tool, arguments, world)
            if guarded is not None:
                return guarded
        return None

    def transform_outcome(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome, world: World
    ) -> ToolOutcome:
        current = self._fault.transform_outcome(tool, arguments, outcome, world)
        for guard in self._guards:
            current = guard.transform_outcome(tool, arguments, current, world)
        return current


class RepairEvaluation(BaseModel):
    """Measured performance of one repair. Both numbers are mandatory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repair: RepairSpec
    incident_trials: int = Field(gt=0)
    incident_prevented: int = Field(ge=0)
    normal_cases: int = Field(ge=0)
    normal_cases_broken: int = Field(ge=0)

    @property
    def prevention_rate(self) -> float:
        return self.incident_prevented / self.incident_trials

    @property
    def false_block_rate(self) -> float:
        return self.normal_cases_broken / self.normal_cases if self.normal_cases else 0.0

    @property
    def acceptable(self) -> bool:
        """Prevents the incident without breaking a single normal case."""
        return self.prevention_rate == 1.0 and self.false_block_rate == 0.0


def evaluate_repair(
    spec: RepairSpec,
    *,
    scenario_id: str,
    seed: int,
    injection: InjectionSpec | None,
    normal_case_ids: tuple[str, ...],
    trials: int = 5,
    engine: ReplayEngine | None = None,
) -> RepairEvaluation:
    """Measure a repair against the incident and against the normal cases."""
    engine = engine or ReplayEngine()

    prevented = 0
    for _ in range(trials):
        result = _run_guarded(engine, spec, scenario_id, seed, injection)
        prevented += int(result.trace.outcome.status is not OutcomeStatus.FAIL)

    broken = 0
    for normal_id in normal_case_ids:
        result = _run_guarded(engine, spec, normal_id, seed, None)
        broken += int(result.trace.outcome.status is OutcomeStatus.FAIL)

    return RepairEvaluation(
        repair=spec,
        incident_trials=trials,
        incident_prevented=prevented,
        normal_cases=len(normal_case_ids),
        normal_cases_broken=broken,
    )


def _run_guarded(
    engine: ReplayEngine,
    spec: RepairSpec,
    scenario_id: str,
    seed: int,
    injection: InjectionSpec | None,
):
    from aftermath.companyagent.scenarios import get_scenario
    from aftermath.companyagent.simple import SimpleCustomerOpsAgent
    from aftermath.companyagent.world import build_world

    fault = Injector(injection) if injection else NullInjector()
    guard = _GuardAdapter(RepairGuard(spec, fault))
    agent = SimpleCustomerOpsAgent(None, narrate=False, injector=guard)
    return agent.run(get_scenario(scenario_id), build_world(seed))


class _GuardAdapter:
    """Routes the agent's pre-execution hook through the guard's world-aware check."""

    def __init__(self, guard: RepairGuard) -> None:
        self._guard = guard
        self._world: World | None = None

    @property
    def fired(self) -> bool:
        return self._guard.fired

    def ground_truth(self):
        return self._guard.ground_truth()

    def prepare_world(self, world: World) -> World:
        self._world = world
        return self._guard.prepare_world(world)

    def override_call(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome | None:
        if self._world is not None:
            guarded = self._guard.guard_before_call(tool, arguments, self._world)
            if guarded is not None:
                return guarded
        return self._guard.override_call(tool, arguments)

    def transform_outcome(self, tool, arguments, outcome, world):
        return self._guard.transform_outcome(tool, arguments, outcome, world)

    def extra_calls(self, tool, arguments, outcome):
        return self._guard.extra_calls(tool, arguments, outcome)

    def note_step(self, *, call_step: str, result_step: str) -> None:
        self._guard.note_step(call_step=call_step, result_step=result_step)
