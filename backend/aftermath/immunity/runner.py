"""Running the immunity suite against an agent version.

An "agent version" here is the monitored agent plus the set of guardrails it
ships with. Replaying every stored case against it answers the question a
release actually needs answered: *does this build still contain a bug we already
paid to fix?*

Deterministic throughout. A case passes when the scenario oracle says the run was
safe — never because a model judged it so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aftermath.companyagent.scenarios import get_scenario
from aftermath.companyagent.simple import SimpleCustomerOpsAgent
from aftermath.companyagent.world import build_world
from aftermath.core.trace import OutcomeStatus
from aftermath.immunity.case import CaseControlsFailed, RegressionCase
from aftermath.injection.injector import Injector
from aftermath.injection.spec import InjectionSpec
from aftermath.replay.repair import GuardChain, RepairSpec


@dataclass(frozen=True)
class AgentVersion:
    """A build under test: the agent plus whichever guardrails it ships."""

    label: str
    repairs: tuple[RepairSpec, ...] = ()

    @classmethod
    def unrepaired(cls) -> AgentVersion:
        return cls(label="unrepaired", repairs=())


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    incident_id: str
    protected: bool
    detail: str
    # Whether the staged fault actually occurred. "Protected" with a fault that
    # never fired is not the same as a guard doing its job — it means the case
    # exercised nothing. Recorded so the difference is visible rather than
    # hidden behind a green tick.
    fault_fired: bool = True

    @property
    def regressed(self) -> bool:
        return not self.protected

    @property
    def vacuous(self) -> bool:
        """Passed, but only because the fault never occurred."""
        return self.protected and not self.fault_fired


@dataclass(frozen=True)
class ImmunityReport:
    """Release gate over the whole suite."""

    version: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def protected(self) -> list[CaseResult]:
        return [r for r in self.results if r.protected]

    @property
    def regressions(self) -> list[CaseResult]:
        return [r for r in self.results if r.regressed]

    @property
    def vacuous(self) -> list[CaseResult]:
        """Cases that passed without their fault ever occurring."""
        return [r for r in self.results if r.vacuous]

    @property
    def release_blocked(self) -> bool:
        """Any regression blocks a release. One returning bug is enough."""
        return bool(self.regressions)

    @property
    def verdict(self) -> str:
        if not self.results:
            return "NO CASES"
        if self.release_blocked:
            return "RELEASE WARNING"
        return "RELEASE OK"

    def summary(self) -> str:
        line = (
            f"{len(self.protected)}/{len(self.results)} protected, "
            f"{len(self.regressions)} regression(s) → {self.verdict}"
        )
        if self.vacuous:
            line += f" [{len(self.vacuous)} vacuous: fault never fired]"
        return line


def _run(
    scenario_id: str,
    seed: int,
    injection: InjectionSpec | None,
    repairs: tuple[RepairSpec, ...],
):
    fault = Injector(injection) if injection else None
    chain = GuardChain(repairs, fault)
    agent = SimpleCustomerOpsAgent(None, narrate=False, injector=_ChainAdapter(chain))
    run = agent.run(get_scenario(scenario_id), build_world(seed))
    return run, bool(fault is None or fault.fired)


class _ChainAdapter:
    """Gives the guard chain access to the world for its pre-execution checks."""

    def __init__(self, chain: GuardChain) -> None:
        self._chain = chain
        self._world = None

    @property
    def fired(self) -> bool:
        return self._chain.fired

    def ground_truth(self):
        return self._chain.ground_truth()

    def prepare_world(self, world):
        self._world = world
        return self._chain.prepare_world(world)

    def override_call(self, tool, arguments):
        if self._world is not None:
            guarded = self._chain.guard_before_call(tool, arguments, self._world)
            if guarded is not None:
                return guarded
        return self._chain.override_call(tool, arguments)

    def transform_outcome(self, tool, arguments, outcome, world):
        return self._chain.transform_outcome(tool, arguments, outcome, world)

    def extra_calls(self, tool, arguments, outcome):
        return self._chain.extra_calls(tool, arguments, outcome)

    def note_step(self, *, call_step, result_step):
        self._chain.note_step(call_step=call_step, result_step=result_step)


def run_case(case: RegressionCase, version: AgentVersion) -> CaseResult:
    """Replay one case against a version. Protected means the failure did not recur."""
    run, fault_fired = _run(case.scenario_id, case.seed, case.injection, version.repairs)
    failed = run.trace.outcome.status is OutcomeStatus.FAIL
    return CaseResult(
        case_id=case.case_id,
        incident_id=case.incident_id,
        protected=not failed,
        detail=run.trace.outcome.detail or run.trace.outcome.oracle,
        fault_fired=fault_fired,
    )


def run_suite(cases: list[RegressionCase], version: AgentVersion) -> ImmunityReport:
    """Replay every case against a version and produce the release gate."""
    return ImmunityReport(
        version=version.label, results=[run_case(case, version) for case in cases]
    )


def verify_case_controls(case: RegressionCase) -> None:
    """Prove the case is meaningful, in both directions.

    Raises:
        CaseControlsFailed: if the case does not fail unrepaired (it detects
            nothing) or does not pass repaired (the repair does not work). Either
            way the case would be a green light that means nothing, and storing
            it would quietly weaken the whole suite.
    """
    unrepaired = run_case(case, AgentVersion.unrepaired())
    if unrepaired.protected:
        raise CaseControlsFailed(
            f"{case.case_id}: passes even against the UNREPAIRED agent — "
            "it cannot detect the bug it exists to catch"
        )

    repaired = run_case(case, AgentVersion("repaired", (case.verified_repair,)))
    if not repaired.protected:
        raise CaseControlsFailed(
            f"{case.case_id}: still fails WITH its verified repair applied "
            f"({repaired.detail}) — the repair does not prevent the incident"
        )
