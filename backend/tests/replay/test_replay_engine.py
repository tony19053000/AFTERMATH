"""Replay determinism, counterfactual interventions, and effect-size ranking.

P4 acceptance:
* strict replay of an unmodified trace reproduces the outcome byte-identically,
* N-trial replay reproduces the incident's failure rate within tolerance,
* intervening at `true_causal_step` measurably reduces the failure rate,
* intervening at an unrelated step does not,
* zero LLM calls inside `replay/` (see `tests/arch/test_import_boundaries.py`),
* experiments are persisted and re-runnable from artifacts.

The positive/negative control pair is the most important thing in this file. An
engine that reported "causal" for every step would be worse than useless, and
only the negative control catches that.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from aftermath.companyagent.scenarios import SCENARIOS
from aftermath.core.trace import StepType, Trace
from aftermath.injection.incidents import load_incidents
from aftermath.injection.runner import run_clean, run_incident
from aftermath.llm.mock import MockProvider
from aftermath.replay import engine as engine_module
from aftermath.replay import experiment as experiment_module
from aftermath.replay.engine import ReplayEngine, ReplayRequest
from aftermath.replay.experiment import (
    ExperimentResult,
    ExperimentRunner,
    TrialSummary,
    localize,
    rank_by_effect,
)
from aftermath.replay.intervention import (
    InterventionKind,
    InterventionSpec,
    TargetNotFoundError,
    addressable_steps,
    resolve_target,
)

INCIDENTS = load_incidents()
INCIDENT_IDS = sorted(INCIDENTS)
SCENARIO_IDS = sorted(SCENARIOS)

TRIALS = 5  # deterministic agent: 5 trials prove as much as 50, far faster


@pytest.fixture(scope="module")
def engine() -> ReplayEngine:
    return ReplayEngine()


@pytest.fixture(scope="module")
def runner() -> ExperimentRunner:
    return ExperimentRunner()


def corrective_intervention(incident_id: str, trace: Trace) -> InterventionSpec:
    """The counterfactual a planner would propose for this incident.

    Written here in P4 so the controls can run; in P5 the counterfactual agent
    proposes it instead. It uses only the trace and a clean run — never the
    injector's internals — so it is a genuine counterfactual, not a
    privileged undo of a fault whose mechanism we already know.
    """
    incident = INCIDENTS[incident_id]
    causal = trace.injection.true_causal_step
    step = trace.step(causal)

    if step.type is StepType.TOOL_CALL:
        # The action itself is the fault: the counterfactual is not doing it.
        return InterventionSpec(kind=InterventionKind.SKIP_TOOL_CALL, step_id=causal)

    for clean_step in run_clean(incident.scenario_id).trace.steps:
        if (
            clean_step.type is StepType.TOOL_RESULT
            and clean_step.tool == step.tool
            and clean_step.result is not None
        ):
            return InterventionSpec(
                kind=InterventionKind.REPLACE_TOOL_RESULT,
                step_id=causal,
                replacement=clean_step.result,
                rationale="value this step would have carried in a healthy run",
            )
    raise AssertionError(f"no natural value available for {incident_id}")


def unrelated_steps(trace: Trace, causal: str) -> list[str]:
    """Addressable steps that are *not* the suspected cause — the control set."""
    return [
        step_id
        for step_id in addressable_steps(trace)
        if step_id != causal and trace.step(step_id).result is not None
    ]


class TestStrictReplayIsByteIdentical:
    """The foundational property. Everything downstream depends on it."""

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_clean_run_replays_byte_identically(
        self, engine: ReplayEngine, scenario_id: str
    ) -> None:
        original = run_clean(scenario_id).trace

        replayed = engine.replay(ReplayRequest(scenario_id=scenario_id, seed=1337)).trace

        assert replayed.to_jsonl() == original.to_jsonl()
        assert replayed.content_hash() == original.content_hash()

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_incident_replays_byte_identically(
        self, engine: ReplayEngine, incident_id: str
    ) -> None:
        incident = INCIDENTS[incident_id]
        original = run_incident(incident).run.trace

        replayed = engine.replay(
            ReplayRequest(
                scenario_id=incident.scenario_id,
                seed=incident.replay_configuration.seed,
                injection=incident.injected_failure,
            )
        ).trace

        assert replayed.to_jsonl() == original.to_jsonl()

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_ground_truth_survives_replay(self, engine: ReplayEngine, incident_id: str) -> None:
        incident = INCIDENTS[incident_id]
        original = run_incident(incident).run.trace

        replayed = engine.replay(
            ReplayRequest(
                scenario_id=incident.scenario_id,
                seed=1337,
                injection=incident.injected_failure,
            )
        ).trace

        assert replayed.injection.true_causal_step == original.injection.true_causal_step

    def test_replay_with_mock_provider_is_deterministic(self, engine: ReplayEngine) -> None:
        """With narration on, a deterministic provider keeps replay identical."""
        request = ReplayRequest(
            scenario_id="refund_in_window", seed=1337, provider=MockProvider()
        )

        assert engine.replay(request).trace.to_jsonl() == engine.replay(request).trace.to_jsonl()

    def test_different_seed_produces_a_different_run(self, engine: ReplayEngine) -> None:
        a = engine.replay(ReplayRequest(scenario_id="refund_in_window", seed=1337))
        b = engine.replay(ReplayRequest(scenario_id="refund_in_window", seed=4242))

        assert a.content_hash != b.content_hash


class TestFailureRateReproduction:
    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_baseline_failure_rate_matches_the_incident(
        self, runner: ExperimentRunner, incident_id: str
    ) -> None:
        incident = INCIDENTS[incident_id]
        summary, _ = runner._measure(
            incident.scenario_id, 1337, incident.injected_failure, (), TRIALS
        )

        assert summary.failure_rate == 1.0
        assert summary.deterministic, "unexpected variance in a deterministic configuration"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_clean_baseline_never_fails(
        self, runner: ExperimentRunner, scenario_id: str
    ) -> None:
        summary, _ = runner._measure(scenario_id, 1337, None, (), TRIALS)

        assert summary.failure_rate == 0.0


class TestCausalControls:
    """The heart of P4: does the evidence actually discriminate?"""

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_positive_control_intervening_at_the_true_cause_prevents_failure(
        self, runner: ExperimentRunner, incident_id: str
    ) -> None:
        incident = INCIDENTS[incident_id]
        trace = run_incident(incident).run.trace

        result = runner.run(
            scenario_id=incident.scenario_id,
            seed=1337,
            injection=incident.injected_failure,
            intervention=corrective_intervention(incident_id, trace),
            trials=TRIALS,
            incident_id=incident_id,
        )

        assert result.baseline.failure_rate == 1.0
        assert result.intervened.failure_rate == 0.0
        assert result.effect_size == pytest.approx(1.0)
        assert result.prevented

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_negative_control_unrelated_steps_have_no_effect(
        self, runner: ExperimentRunner, incident_id: str
    ) -> None:
        """An engine that 'fixes' everything proves nothing."""
        incident = INCIDENTS[incident_id]
        trace = run_incident(incident).run.trace
        causal = trace.injection.true_causal_step

        others = unrelated_steps(trace, causal)
        assert others, "no unrelated steps available to control against"

        for step_id in others:
            result = runner.run(
                scenario_id=incident.scenario_id,
                seed=1337,
                injection=incident.injected_failure,
                intervention=InterventionSpec(
                    kind=InterventionKind.REPLACE_TOOL_RESULT,
                    step_id=step_id,
                    replacement=trace.step(step_id).result,
                ),
                trials=TRIALS,
                incident_id=incident_id,
            )

            assert result.effect_size == 0.0, (
                f"{incident_id}: intervening at unrelated {step_id} changed the outcome"
            )

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_localization_picks_the_true_causal_step(
        self, runner: ExperimentRunner, incident_id: str
    ) -> None:
        incident = INCIDENTS[incident_id]
        trace = run_incident(incident).run.trace
        causal = trace.injection.true_causal_step

        results = [
            runner.run(
                scenario_id=incident.scenario_id,
                seed=1337,
                injection=incident.injected_failure,
                intervention=corrective_intervention(incident_id, trace),
                trials=TRIALS,
                incident_id=incident_id,
            )
        ]
        for step_id in unrelated_steps(trace, causal)[:3]:
            results.append(
                runner.run(
                    scenario_id=incident.scenario_id,
                    seed=1337,
                    injection=incident.injected_failure,
                    intervention=InterventionSpec(
                        kind=InterventionKind.REPLACE_TOOL_RESULT,
                        step_id=step_id,
                        replacement=trace.step(step_id).result,
                    ),
                    trials=TRIALS,
                    incident_id=incident_id,
                )
            )

        assert localize(results) == causal

    def test_localize_returns_none_when_nothing_clears_the_bar(self) -> None:
        """No evidence is a legitimate answer; inventing one is not."""
        weak = [
            ExperimentResult(
                experiment_id="e",
                intervention=InterventionSpec(
                    kind=InterventionKind.SKIP_TOOL_CALL, step_id="s0001"
                ),
                baseline=TrialSummary(trials=5, failures=5),
                intervened=TrialSummary(trials=5, failures=5),
            )
        ]

        assert localize(weak) is None


class TestRankingUsesEvidenceOnly:
    def test_ranking_ignores_confidence(self) -> None:
        """A confident wrong hypothesis must lose to a diffident right one.

        This single assertion is the difference between AFTERMATH and an LLM
        that guesses root causes.
        """
        confident_but_wrong = ExperimentResult(
            experiment_id="wrong",
            intervention=InterventionSpec(
                kind=InterventionKind.SKIP_TOOL_CALL, step_id="s0002"
            ),
            baseline=TrialSummary(trials=10, failures=10),
            intervened=TrialSummary(trials=10, failures=10),
            proposer_confidence=0.99,
        )
        diffident_but_right = ExperimentResult(
            experiment_id="right",
            intervention=InterventionSpec(
                kind=InterventionKind.SKIP_TOOL_CALL, step_id="s0007"
            ),
            baseline=TrialSummary(trials=10, failures=10),
            intervened=TrialSummary(trials=10, failures=0),
            proposer_confidence=0.05,
        )

        ranked = rank_by_effect([confident_but_wrong, diffident_but_right])

        assert ranked[0].experiment_id == "right"
        assert localize(ranked) == "s0007"

    def test_ranking_is_stable_for_equal_effects(self) -> None:
        def result(step: str) -> ExperimentResult:
            return ExperimentResult(
                experiment_id=step,
                intervention=InterventionSpec(
                    kind=InterventionKind.SKIP_TOOL_CALL, step_id=step
                ),
                baseline=TrialSummary(trials=2, failures=2),
                intervened=TrialSummary(trials=2, failures=1),
            )

        assert [r.intervention.step_id for r in rank_by_effect([result("s9"), result("s1")])] == [
            "s1",
            "s9",
        ]


class TestInterventionResolution:
    def test_resolve_accepts_call_or_result_step(self) -> None:
        trace = run_incident(INCIDENTS["I-001"]).run.trace
        result_step = next(
            s for s in trace.steps if s.type is StepType.TOOL_RESULT and s.tool == "get_policy"
        )
        call_step = next(
            s for s in trace.steps if s.type is StepType.TOOL_CALL and s.tool == "get_policy"
        )

        assert resolve_target(trace, result_step.step_id).tool == "get_policy"
        assert resolve_target(trace, call_step.step_id).occurrence == 1

    def test_unknown_step_raises(self) -> None:
        trace = run_incident(INCIDENTS["I-001"]).run.trace

        with pytest.raises(TargetNotFoundError):
            resolve_target(trace, "s9999")

    def test_non_tool_step_raises(self) -> None:
        trace = run_incident(INCIDENTS["I-001"]).run.trace
        reasoning = next(s for s in trace.steps if s.type is StepType.AGENT_REASONING)

        with pytest.raises(TargetNotFoundError):
            resolve_target(trace, reasoning.step_id)

    def test_replace_requires_a_replacement(self) -> None:
        with pytest.raises(ValueError, match="requires a `replacement`"):
            InterventionSpec(kind=InterventionKind.REPLACE_TOOL_RESULT, step_id="s0001")

    def test_intervention_targeting_a_missing_step_raises(self, engine: ReplayEngine) -> None:
        with pytest.raises(TargetNotFoundError):
            engine.replay(
                ReplayRequest(
                    scenario_id="refund_in_window",
                    seed=1337,
                    interventions=(
                        InterventionSpec(
                            kind=InterventionKind.SKIP_TOOL_CALL, step_id="s9999"
                        ),
                    ),
                )
            )

    def test_skip_prevents_the_state_mutation(self, engine: ReplayEngine) -> None:
        """Post-hoc result rewriting cannot undo an action; skipping can."""
        incident = INCIDENTS["I-002"]
        trace = run_incident(incident).run.trace
        duplicate = [
            s
            for s in trace.steps
            if s.type is StepType.TOOL_CALL and s.tool == "issue_simulated_refund"
        ][1]

        result = engine.replay(
            ReplayRequest(
                scenario_id=incident.scenario_id,
                seed=1337,
                injection=incident.injected_failure,
                interventions=(
                    InterventionSpec(
                        kind=InterventionKind.SKIP_TOOL_CALL, step_id=duplicate.step_id
                    ),
                ),
            )
        )

        assert len(result.world.refunds) == 1
        assert not result.failed


class TestExperimentArtifacts:
    def test_artifact_carries_every_reported_number(self) -> None:
        incident = INCIDENTS["I-001"]
        trace = run_incident(incident).run.trace
        result = ExperimentRunner().run(
            scenario_id=incident.scenario_id,
            seed=1337,
            injection=incident.injected_failure,
            intervention=corrective_intervention("I-001", trace),
            trials=TRIALS,
            incident_id="I-001",
        )

        artifact = result.to_artifact()

        assert artifact["effect_size"] == result.effect_size
        assert artifact["baseline_failure_rate"] == 1.0
        assert artifact["intervened_failure_rate"] == 0.0
        assert artifact["artifact_hash"].startswith("sha256:")

    def test_artifact_round_trips_and_is_rerunnable(self, tmp_path: Path) -> None:
        """A stored experiment must be re-derivable, not just re-readable."""
        incident = INCIDENTS["I-003"]
        trace = run_incident(incident).run.trace
        original = ExperimentRunner().run(
            scenario_id=incident.scenario_id,
            seed=1337,
            injection=incident.injected_failure,
            intervention=corrective_intervention("I-003", trace),
            trials=TRIALS,
            incident_id="I-003",
        )

        path = tmp_path / "experiment.json"
        path.write_text(json.dumps(original.to_artifact()), encoding="utf-8")
        stored = json.loads(path.read_text(encoding="utf-8"))

        rerun = ExperimentRunner().run(
            scenario_id=incident.scenario_id,
            seed=1337,
            injection=incident.injected_failure,
            intervention=InterventionSpec.model_validate(stored["intervention"]),
            trials=TRIALS,
            incident_id="I-003",
        )

        assert rerun.experiment_id == original.experiment_id
        assert rerun.effect_size == original.effect_size

    def test_experiment_id_is_deterministic_and_configuration_bound(self) -> None:
        incident = INCIDENTS["I-001"]
        trace = run_incident(incident).run.trace
        intervention = corrective_intervention("I-001", trace)

        def run(trials: int) -> str:
            return ExperimentRunner().run(
                scenario_id=incident.scenario_id,
                seed=1337,
                injection=incident.injected_failure,
                intervention=intervention,
                trials=trials,
            ).experiment_id

        assert run(TRIALS) == run(TRIALS)
        assert run(TRIALS) != run(TRIALS + 1)


class TestNoModelInTheEvidencePath:
    def test_replay_modules_import_no_llm(self) -> None:
        for module in (engine_module, experiment_module):
            assert "aftermath.llm" not in inspect.getsource(module)

    def test_engine_runs_with_no_provider_at_all(self, engine: ReplayEngine) -> None:
        result = engine.replay(ReplayRequest(scenario_id="refund_in_window", seed=1337))

        assert result.trace.steps
        assert not result.failed

    def test_outcome_comes_from_the_oracle_not_a_model(self, engine: ReplayEngine) -> None:
        incident = INCIDENTS["I-001"]

        result = engine.replay(
            ReplayRequest(
                scenario_id=incident.scenario_id,
                seed=1337,
                injection=incident.injected_failure,
            )
        )

        assert result.failed
        assert result.trace.outcome.oracle == incident.failing_oracle
