"""Grader correctness, baseline fairness, and metric integrity.

P7 acceptance:
* baseline and AFTERMATH receive an identical incident set and the identical grader,
* every reported number is read from a stored artifact — none computed by an LLM
  or by hand,
* results are reproducible,
* the baseline prompt is fair (reviewed and recorded in DECISIONS).

The grader is the most dangerous component in the project: a subtly generous one
would manufacture a win. Its near-miss handling is tested hardest.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from aftermath.benchmark import grader as grader_module
from aftermath.benchmark import metrics as metrics_module
from aftermath.benchmark import runner as runner_module
from aftermath.benchmark.baseline import BaselineDiagnosis, PROMPT_PATH, diagnose
from aftermath.benchmark.grader import GradedAnswer, Verdict, causal_set, grade
from aftermath.benchmark.metrics import Comparison, SystemMetrics, summarize
from aftermath.benchmark.runner import AFTERMATH, BASELINE, run_benchmark
from aftermath.injection.incidents import load_incidents
from aftermath.injection.runner import run_incident
from aftermath.llm.mock import MockProvider

INCIDENTS = load_incidents()
INCIDENT_IDS = sorted(INCIDENTS)
SAMPLE = ["I-001", "I-002", "I-003"]


def truth_of(incident_id: str) -> str:
    return run_incident(INCIDENTS[incident_id]).run.trace.injection.true_causal_step


class TestIncidentSet:
    def test_set_meets_the_planned_size(self) -> None:
        assert len(INCIDENTS) >= 15, "P7 targets 15-20 incidents"

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_every_incident_reproduces_and_fails_its_declared_oracle(
        self, incident_id: str
    ) -> None:
        incident = INCIDENTS[incident_id]
        trace = run_incident(incident).run.trace

        assert trace.outcome.status.value == "FAIL"
        assert trace.outcome.oracle == incident.failing_oracle

    def test_incidents_span_multiple_fault_mechanisms(self) -> None:
        """A benchmark of one mechanism repeated would measure almost nothing."""
        kinds = {i.injected_failure.kind for i in INCIDENTS.values()}
        scenarios = {i.scenario_id for i in INCIDENTS.values()}

        assert len(kinds) >= 4
        assert len(scenarios) >= 3


class TestGrader:
    """Only an exact match counts. Everything else is reported, not credited."""

    @pytest.mark.parametrize("incident_id", SAMPLE)
    def test_exact_match_is_correct(self, incident_id: str) -> None:
        result = grade(INCIDENTS[incident_id], "t", truth_of(incident_id))

        assert result.verdict is Verdict.EXACT
        assert result.correct

    @pytest.mark.parametrize("incident_id", SAMPLE)
    def test_no_answer_is_not_correct(self, incident_id: str) -> None:
        result = grade(INCIDENTS[incident_id], "t", None)

        assert result.verdict is Verdict.NO_ANSWER
        assert not result.correct

    @pytest.mark.parametrize("incident_id", SAMPLE)
    def test_unrelated_step_is_wrong(self, incident_id: str) -> None:
        result = grade(INCIDENTS[incident_id], "t", "s9999")

        assert result.verdict is Verdict.WRONG
        assert not result.correct

    def test_downstream_step_is_a_near_miss_and_still_not_correct(self) -> None:
        """The generosity trap: a near miss must never count as a success.

        In I-001 correcting s0009 also prevents the failure, so it is genuinely
        causal — but it is not the root cause, and crediting it would flatter
        whichever system answers downstream.
        """
        members = causal_set("I-001")
        truth = truth_of("I-001")
        downstream = [s for s in members if s != truth]
        assert downstream, "expected a causal chain in I-001"

        result = grade(INCIDENTS["I-001"], "t", downstream[0])

        assert result.verdict is Verdict.NEAR_MISS
        assert not result.correct

    def test_causal_set_always_contains_the_true_cause(self) -> None:
        for incident_id in SAMPLE:
            assert truth_of(incident_id) in causal_set(incident_id)

    def test_causal_set_is_deterministic(self) -> None:
        causal_set.cache_clear()
        first = causal_set("I-001")
        causal_set.cache_clear()

        assert causal_set("I-001") == first

    def test_grader_makes_no_llm_call(self) -> None:
        assert "aftermath.llm" not in inspect.getsource(grader_module)
        assert "aftermath.llm" not in inspect.getsource(metrics_module)

    def test_both_systems_graded_by_the_same_function(self) -> None:
        """One implementation, or the comparison means nothing."""
        source = inspect.getsource(runner_module)

        assert source.count("grade(") >= 2
        assert "def grade" not in source


class TestBaselineFairness:
    """D-007: a strawman baseline would invalidate the entire result."""

    def test_prompt_is_substantive_and_gives_real_guidance(self) -> None:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")

        assert len(prompt) > 600
        # It must actually teach the hard part: cause precedes consequence.
        assert "Causes precede consequences" in prompt
        assert "PRODUCED" in prompt and "CONSUMED" in prompt
        assert "duplicate" in prompt

    def test_baseline_receives_the_same_redacted_trace_as_aftermath(self) -> None:
        source = inspect.getsource(runner_module) + inspect.getsource(
            inspect.getmodule(diagnose)
        )

        assert "redact_for_agent" in source

    def test_baseline_never_sees_ground_truth(self) -> None:
        seen: list[str] = []

        class Capturing:
            name = "capturing"

            def complete(self, request):
                seen.append(request.prompt)
                raise RuntimeError("stop")

        trace = run_incident(INCIDENTS["I-001"]).run.trace
        diagnose(Capturing(), "I-001", trace)

        assert seen
        assert "true_causal_step" not in seen[0]
        assert "injection" not in seen[0]

    def test_baseline_output_schema_matches_what_is_graded(self) -> None:
        assert "root_cause_step_id" in BaselineDiagnosis.model_fields

    def test_provider_failure_is_recorded_not_raised(self) -> None:
        class Broken:
            name = "broken"

            def complete(self, request):
                raise ConnectionError("network down")

        trace = run_incident(INCIDENTS["I-001"]).run.trace
        result = diagnose(Broken(), "I-001", trace)

        assert not result.answered
        assert "ConnectionError" in result.error

    def test_unparseable_answer_is_recorded_not_guessed(self) -> None:
        trace = run_incident(INCIDENTS["I-001"]).run.trace

        result = diagnose(MockProvider(), "I-001", trace)

        assert not result.answered
        assert result.error


class TestMetrics:
    def _answers(self, verdicts: list[Verdict]) -> list[GradedAnswer]:
        return [
            GradedAnswer(
                incident_id=f"I-{i:03d}",
                system="s",
                answered_step="s0001",
                true_causal_step="s0001",
                verdict=v,
            )
            for i, v in enumerate(verdicts)
        ]

    def test_localization_rate_counts_only_exact(self) -> None:
        metrics = summarize(
            "s", self._answers([Verdict.EXACT, Verdict.NEAR_MISS, Verdict.WRONG, Verdict.EXACT])
        )

        assert metrics.localization_rate == 0.5
        assert metrics.near_miss_rate == 0.25
        assert metrics.in_causal_set_rate == 0.75

    def test_empty_run_raises_rather_than_reporting_zero(self) -> None:
        """0.0 would read as a measured failure rather than as no data."""
        with pytest.raises(ValueError, match="nothing to summarize"):
            summarize("s", [])

    def test_comparison_reports_a_baseline_win_honestly(self) -> None:
        """The result must be reportable when AFTERMATH loses."""
        losing = Comparison(
            aftermath=SystemMetrics(system=AFTERMATH, incidents=4, exact=1, near_miss=0,
                                    wrong=3, no_answer=0),
            baseline=SystemMetrics(system=BASELINE, incidents=4, exact=3, near_miss=0,
                                   wrong=1, no_answer=0),
            incident_ids=("I-001", "I-002", "I-003", "I-004"),
        )

        assert losing.delta < 0
        assert losing.verdict == "BASELINE ahead"

    def test_artifact_carries_every_reported_number(self) -> None:
        comparison = Comparison(
            aftermath=SystemMetrics(system=AFTERMATH, incidents=2, exact=2, near_miss=0,
                                    wrong=0, no_answer=0),
            baseline=SystemMetrics(system=BASELINE, incidents=2, exact=1, near_miss=1,
                                   wrong=0, no_answer=0),
            incident_ids=("I-001", "I-002"),
        )

        artifact = comparison.to_artifact()

        assert artifact["aftermath_localization_rate"] == 1.0
        assert artifact["baseline_localization_rate"] == 0.5
        assert artifact["delta"] == 0.5
        assert artifact["artifact_hash"].startswith("sha256:")


class TestBenchmarkRun:
    def test_identical_incident_set_for_both_systems(self) -> None:
        """Fairness enforced structurally: one list, both systems."""
        subset = {k: INCIDENTS[k] for k in SAMPLE}

        comparison = run_benchmark(None, incidents=subset, trials=2)

        assert comparison.incident_ids == tuple(sorted(subset))
        assert comparison.aftermath.incidents == comparison.baseline.incidents == len(subset)

    def test_deterministic_path_is_reproducible(self) -> None:
        subset = {k: INCIDENTS[k] for k in SAMPLE}

        a = run_benchmark(None, incidents=subset, trials=2).to_artifact()
        b = run_benchmark(None, incidents=subset, trials=2).to_artifact()

        # Wall-clock latency legitimately varies; everything else must not.
        assert a["artifact_hash"] == b["artifact_hash"]
        assert a["aftermath_localization_rate"] == b["aftermath_localization_rate"]
        assert a["delta"] == b["delta"]

    def test_latency_is_reported_but_excluded_from_the_hash(self) -> None:
        """Otherwise no two artifacts of the same result would ever match."""
        subset = {k: INCIDENTS[k] for k in SAMPLE}

        a = run_benchmark(None, incidents=subset, trials=2).to_artifact()
        b = run_benchmark(None, incidents=subset, trials=2).to_artifact()

        assert a["artifact_hash"] == b["artifact_hash"]
        assert "latency_seconds" in a["aftermath"]

    def test_artifact_is_written_and_reloadable(self, tmp_path: Path) -> None:
        subset = {k: INCIDENTS[k] for k in SAMPLE}
        path = tmp_path / "bench.json"

        comparison = run_benchmark(None, incidents=subset, trials=2, artifact_path=path)
        stored = json.loads(path.read_text(encoding="utf-8"))

        assert stored["aftermath_localization_rate"] == comparison.aftermath.localization_rate
        assert len(stored["per_incident"]) == len(subset)
        assert {r["incident_id"] for r in stored["per_incident"]} == set(subset)

    def test_baseline_without_a_provider_scores_zero_not_an_error(self) -> None:
        """With no provider the baseline cannot answer; that is data, not a crash."""
        subset = {k: INCIDENTS[k] for k in SAMPLE}

        comparison = run_benchmark(None, incidents=subset, trials=2)

        assert comparison.baseline.no_answer == len(subset)
        assert comparison.baseline.localization_rate == 0.0


class TestCommittedBenchmarkArtifacts:
    """The published result must be re-derivable from what is in the repository."""

    RESULTS = Path(__file__).resolve().parents[3] / "data" / "results" / "benchmark.json"
    CASSETTE = Path(__file__).resolve().parents[3] / "data" / "cassettes" / "benchmark.json"

    def test_result_artifact_is_committed_and_complete(self) -> None:
        payload = json.loads(self.RESULTS.read_text(encoding="utf-8"))

        assert len(payload["per_incident"]) == len(INCIDENTS)
        assert payload["artifact_hash"].startswith("sha256:")
        for key in ("aftermath_localization_rate", "baseline_localization_rate", "delta"):
            assert key in payload

    def test_every_published_number_traces_to_the_artifact(self) -> None:
        """README/STATUS quote these; they must come from the file, not from prose."""
        payload = json.loads(self.RESULTS.read_text(encoding="utf-8"))

        assert payload["aftermath_localization_rate"] == 0.90
        assert payload["baseline_localization_rate"] == 0.90
        assert payload["verdict"] == "TIED"

    def test_the_p7_result_is_preserved_as_a_historical_record(self) -> None:
        """A superseded result is kept, not overwritten.

        P8.1 changed the orchestration, so the P7 numbers are no longer
        reproducible by current code. They remain on disk because the
        before/after comparison is the evidence that the fix worked.
        """
        p7 = json.loads(
            (self.RESULTS.parent / "benchmark_p7_pre_fallback.json").read_text("utf-8")
        )
        current = json.loads(self.RESULTS.read_text(encoding="utf-8"))

        assert p7["aftermath_localization_rate"] == 0.75
        assert current["aftermath_localization_rate"] == 0.90
        # The baseline is untouched by the change, which is what makes the
        # comparison attributable to the orchestration fix.
        assert p7["baseline_localization_rate"] == current["baseline_localization_rate"]

    def test_cassette_is_committed_and_secret_free(self) -> None:
        text = self.CASSETTE.read_text(encoding="utf-8")

        assert len(text) > 1000
        for marker in ("GEMINI_API_KEY", "x-goog-api-key", "AQ.Ab8"):
            assert marker not in text

    @pytest.mark.slow
    def test_benchmark_replays_offline_to_the_same_result(self) -> None:
        """The reproducibility claim, asserted rather than asserted-about.

        Replaying from the committed cassette with NO provider instance
        reproduces the published artifact hash exactly.
        """
        from aftermath.llm.recording import RecordingProvider, RecordMode

        offline = RecordingProvider(None, self.CASSETTE, RecordMode.REPLAY)
        comparison = run_benchmark(offline, trials=3, model="gemini-3.7-flash")
        published = json.loads(self.RESULTS.read_text(encoding="utf-8"))

        assert comparison.to_artifact()["artifact_hash"] == published["artifact_hash"]


class TestSweepFallback:
    """P8.1: agents that propose nothing measurable must not cost accuracy."""

    def test_fallback_is_recorded_distinctly_from_an_agent_find(self) -> None:
        """A cause found by the sweep must never be credited to the agent."""
        from aftermath.forensics.orchestrator import ForensicOrchestrator, HypothesisSource
        from aftermath.llm.mock import MockProvider

        # Agent names a real step that is not causal, so nothing survives.
        scripted = MockProvider(
            scripted={
                "forensics:investigator": json.dumps(
                    {"hypotheses": [{"suspected_step_id": "s0003", "mechanism": "wrong"}]}
                )
            }
        )

        report = ForensicOrchestrator(scripted, trials=2).investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.AGENT_THEN_SWEEP
        assert report.root_cause_step == truth_of("I-001")
        assert any("exhaustive sweep" in e for e in report.agent_errors)

    def test_a_correct_agent_hypothesis_does_not_trigger_the_sweep(self) -> None:
        from aftermath.forensics.orchestrator import ForensicOrchestrator, HypothesisSource
        from aftermath.llm.mock import MockProvider

        scripted = MockProvider(
            scripted={
                "forensics:investigator": json.dumps(
                    {"hypotheses": [{"suspected_step_id": truth_of("I-001"), "mechanism": "m"}]}
                )
            }
        )

        report = ForensicOrchestrator(scripted, trials=2).investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.AGENT


class TestAgentCountSweep:
    """P8.2 harness. D-008: agent count is a result, not a design input."""

    def test_lens_selection_is_stable_and_prefix_ordered(self) -> None:
        """N investigators must mean the same first N lenses, every run."""
        from aftermath.forensics.agents import lenses_for

        assert lenses_for(1) == (None,)
        assert lenses_for(3) == lenses_for(5)[:3]

    def test_one_investigator_is_the_existing_unlensed_system(self) -> None:
        """The N=1 arm must be the system already measured, not a new variant."""
        from aftermath.forensics.agents import lenses_for

        assert lenses_for(1) == (None,)

    def test_too_many_investigators_raises(self) -> None:
        from aftermath.forensics.agents import lenses_for

        with pytest.raises(ValueError, match="only 5 lenses"):
            lenses_for(99)

    def test_every_lens_prompt_exists_and_is_distinct(self) -> None:
        from aftermath.forensics.agents import LENS_ORDER, load_lens

        texts = {name: load_lens(name) for name in LENS_ORDER}

        assert len(set(texts.values())) == len(LENS_ORDER), "lenses must differ"
        for text in texts.values():
            assert text.startswith("LENS:")

    def test_investigator_count_is_configuration_not_hard_coded(self) -> None:
        from aftermath.forensics.orchestrator import ForensicOrchestrator

        assert "investigators" in inspect.signature(ForensicOrchestrator.__init__).parameters

    def test_hypotheses_are_unioned_and_deduped_across_lenses(self) -> None:
        """Distinct lenses overlap; the union is what the engine tests."""
        from aftermath.forensics.orchestrator import ForensicOrchestrator, HypothesisSource
        from aftermath.llm.mock import MockProvider

        truth = truth_of("I-001")
        scripted = MockProvider()
        for lens in ("tool_api", "context_memory", "state_systems"):
            scripted.script(
                f"forensics:investigator:{lens}",
                json.dumps({"hypotheses": [{"suspected_step_id": truth, "mechanism": lens}]}),
            )

        report = ForensicOrchestrator(
            scripted, trials=2, investigators=3, run_verifier=False
        ).investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.AGENT
        # Three agents, one shared answer -> one hypothesis, not three.
        assert [h.suspected_step_id for h in report.hypotheses] == [truth]

    def test_marginal_gain_exposes_cost_without_benefit(self) -> None:
        """The comparison the sweep exists to make."""
        from aftermath.benchmark.sweep import ArmResult, SweepReport

        report = SweepReport(
            arms=[
                ArmResult(investigators=1, incidents=10, recall_hits=8, localized=9,
                          fallbacks=2, prompt_tokens=1000, completion_tokens=200),
                ArmResult(investigators=3, incidents=10, recall_hits=8, localized=9,
                          fallbacks=2, prompt_tokens=3000, completion_tokens=600),
            ],
            incident_ids=tuple(f"I-{i:03d}" for i in range(10)),
        )

        gain = report.marginal_gain()[0]

        assert gain["recall_delta"] == 0.0
        assert gain["token_multiple"] == 3.0
