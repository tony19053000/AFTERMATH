"""Running incidents and normal cases.

Deliberately deterministic Python: it runs the monitored agent, applies a fault,
and reports what the oracle said. It makes no causal claim — establishing that
the injected fault *caused* the failure is P4's job, by experiment.
"""

from __future__ import annotations

from dataclasses import dataclass

from aftermath.companyagent.base import AgentRun
from aftermath.companyagent.scenarios import SCENARIOS, get_scenario
from aftermath.companyagent.simple import SimpleCustomerOpsAgent
from aftermath.companyagent.world import build_world
from aftermath.core.trace import OutcomeStatus
from aftermath.injection.incidents import IncidentDefinition
from aftermath.injection.injector import Injector
from aftermath.llm.base import LLMProvider

# The clean scenarios double as the normal-case set: P5 measures whether a repair
# breaks them (false-block rate), so they must stay genuinely non-failing.
NORMAL_CASES: tuple[str, ...] = tuple(sorted(SCENARIOS))


@dataclass(frozen=True)
class IncidentRun:
    """One execution of an incident."""

    incident_id: str
    run: AgentRun
    injector_fired: bool

    @property
    def failed(self) -> bool:
        return self.run.trace.outcome.status is OutcomeStatus.FAIL

    @property
    def true_causal_step(self) -> str | None:
        injection = self.run.trace.injection
        return injection.true_causal_step if injection else None


def run_incident(
    incident: IncidentDefinition,
    *,
    provider: LLMProvider | None = None,
    seed: int | None = None,
) -> IncidentRun:
    """Execute an incident with its fault applied.

    Raises:
        RuntimeError: if the injection never fired. A "reproduced" incident whose
            fault never applied would be a false negative masquerading as data.
    """
    injector = Injector(incident.injected_failure)
    agent = SimpleCustomerOpsAgent(provider, narrate=provider is not None, injector=injector)
    world = build_world(seed if seed is not None else incident.replay_configuration.seed)
    run = agent.run(get_scenario(incident.scenario_id), world)

    if not injector.fired:
        raise RuntimeError(
            f"incident {incident.incident_id!r}: injection "
            f"{incident.injected_failure.kind.value!r} never fired"
        )
    return IncidentRun(incident_id=incident.incident_id, run=run, injector_fired=True)


def run_clean(
    scenario_id: str,
    *,
    provider: LLMProvider | None = None,
    seed: int = 1337,
) -> AgentRun:
    """Execute a scenario with no fault applied."""
    agent = SimpleCustomerOpsAgent(provider, narrate=provider is not None)
    return agent.run(get_scenario(scenario_id), build_world(seed))


def failure_rate(
    incident: IncidentDefinition,
    *,
    trials: int | None = None,
    provider: LLMProvider | None = None,
) -> float:
    """Fraction of trials in which the incident's oracle failed.

    Under the current fully-deterministic agent this is 0.0 or 1.0 — every trial
    is identical. It is measured rather than assumed so that the number stays
    honest when P4 introduces resampled replay and real variance appears.
    """
    count = trials if trials is not None else incident.replay_configuration.trials
    failures = sum(1 for _ in range(count) if run_incident(incident, provider=provider).failed)
    return failures / count
