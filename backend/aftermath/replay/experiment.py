"""Counterfactual experiments and effect-size ranking.

This is where a hypothesis stops being an opinion. For each candidate step we run
the incident with and without an intervention at that step, and measure the
change in failure rate:

    effect_size = failure_rate(baseline) - failure_rate(intervened)

A large positive effect means correcting that step prevented the failure. Near
zero means the step was irrelevant, however confident the agent that proposed it
happened to be.

**Ranking uses effect size only.** Agent confidence is carried through for the
record and is deliberately never consulted — that is the difference between this
system and an LLM that guesses. Enforced by `test_ranking_ignores_confidence`.

No LLM calls occur in this module.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.hashing import content_hash
from aftermath.injection.spec import InjectionSpec
from aftermath.replay.engine import ReplayEngine, ReplayRequest
from aftermath.replay.intervention import InterventionSpec


class TrialSummary(BaseModel):
    """Outcome counts over N replays of one configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trials: int = Field(gt=0)
    failures: int = Field(ge=0)
    # Distinct trace hashes seen. 1 means the configuration is fully deterministic;
    # more than 1 means real variance, and the failure rate is a genuine statistic.
    distinct_traces: int = Field(ge=0, default=1)

    @property
    def failure_rate(self) -> float:
        return self.failures / self.trials

    @property
    def deterministic(self) -> bool:
        return self.distinct_traces <= 1


class ExperimentResult(BaseModel):
    """One counterfactual experiment: baseline vs. intervened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    incident_id: str | None = None
    intervention: InterventionSpec
    baseline: TrialSummary
    intervened: TrialSummary
    # Carried for the record only. Never used in ranking.
    proposer_confidence: float | None = None
    applied: bool = True

    @property
    def effect_size(self) -> float:
        """Reduction in failure rate attributable to the intervention."""
        return self.baseline.failure_rate - self.intervened.failure_rate

    @property
    def prevented(self) -> bool:
        """The intervention eliminated the failure entirely."""
        return self.baseline.failures > 0 and self.intervened.failures == 0

    def to_artifact(self) -> dict[str, Any]:
        """Serializable record. Every published number must trace back to one of these."""
        payload = self.model_dump(mode="json")
        payload["effect_size"] = self.effect_size
        payload["prevented"] = self.prevented
        payload["baseline_failure_rate"] = self.baseline.failure_rate
        payload["intervened_failure_rate"] = self.intervened.failure_rate
        payload["artifact_hash"] = content_hash(payload)
        return payload


class ExperimentRunner:
    """Runs counterfactual experiments against the replay engine."""

    def __init__(self, engine: ReplayEngine | None = None) -> None:
        self._engine = engine or ReplayEngine()

    def _measure(
        self,
        scenario_id: str,
        seed: int,
        injection: InjectionSpec | None,
        interventions: tuple[InterventionSpec, ...],
        trials: int,
        provider: Any = None,
    ) -> tuple[TrialSummary, tuple[str, ...]]:
        failures = 0
        hashes: set[str] = set()
        applied: tuple[str, ...] = ()
        for _ in range(trials):
            result = self._engine.replay(
                ReplayRequest(
                    scenario_id=scenario_id,
                    seed=seed,
                    injection=injection,
                    interventions=interventions,
                    provider=provider,
                )
            )
            failures += int(result.failed)
            hashes.add(result.content_hash)
            applied = result.applied_interventions
        return (
            TrialSummary(trials=trials, failures=failures, distinct_traces=len(hashes)),
            applied,
        )

    def run(
        self,
        *,
        scenario_id: str,
        seed: int,
        injection: InjectionSpec | None,
        intervention: InterventionSpec,
        trials: int = 20,
        incident_id: str | None = None,
        proposer_confidence: float | None = None,
        provider: Any = None,
    ) -> ExperimentResult:
        """Measure one intervention against the unintervened baseline."""
        baseline, _ = self._measure(scenario_id, seed, injection, (), trials, provider)
        intervened, applied = self._measure(
            scenario_id, seed, injection, (intervention,), trials, provider
        )
        experiment_id = content_hash(
            {
                "scenario": scenario_id,
                "seed": seed,
                "injection": injection.model_dump(mode="json") if injection else None,
                "intervention": intervention.model_dump(mode="json"),
                "trials": trials,
            }
        )[:23]
        return ExperimentResult(
            experiment_id=experiment_id,
            incident_id=incident_id,
            intervention=intervention,
            baseline=baseline,
            intervened=intervened,
            proposer_confidence=proposer_confidence,
            applied=bool(applied),
        )


def rank_by_effect(results: list[ExperimentResult]) -> list[ExperimentResult]:
    """Order experiments by measured effect, strongest first.

    Ties break on step id for stable, reproducible output. Confidence is not a
    tiebreaker and is not consulted at all: a hypothesis every agent loved and no
    experiment supported must lose to one a single agent proposed with low
    confidence and an experiment confirmed.
    """
    return sorted(results, key=lambda r: (-r.effect_size, r.intervention.step_id))


def localize(results: list[ExperimentResult], threshold: float = 0.5) -> str | None:
    """The step best supported by evidence, or None if nothing clears the bar.

    Returning None is a legitimate outcome: it means no tested intervention
    changed anything, so the evidence does not identify a cause. Reporting a
    best-of-a-bad-set answer would manufacture a finding.
    """
    if not results:
        return None
    best = rank_by_effect(results)[0]
    return best.intervention.step_id if best.effect_size >= threshold else None
