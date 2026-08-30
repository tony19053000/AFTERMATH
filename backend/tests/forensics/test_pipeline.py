"""The forensic pipeline: agent I/O, redaction, and evidence-over-opinion.

P5 acceptance:
* the pipeline runs end to end and the top-ranked cause comes from measured
  effect, never from agent confidence,
* every causal claim cites a concrete experiment artifact,
* a repair is tested against the incident AND against the normal cases,
* the run is reproducible from stored artifacts,
* no LLM output is treated as an experimental result.
"""

from __future__ import annotations

import json

import pytest

from aftermath.core.trace import StepType
from aftermath.forensics.agents import Investigator, load_prompt
from aftermath.forensics.orchestrator import (
    CauseResolution,
    ForensicOrchestrator,
    HypothesisSource,
)
from aftermath.forensics.parsing import AgentOutputError, extract_json, parse_as
from aftermath.forensics.redaction import contains_ground_truth, redact_for_agent
from aftermath.forensics.schemas import InvestigationOutput, PlanOutput, RepairOutput
from aftermath.injection.incidents import load_incidents
from aftermath.injection.runner import NORMAL_CASES, run_incident
from aftermath.llm.mock import MockProvider
from aftermath.replay.repair import RepairKind, RepairSpec, evaluate_repair

INCIDENTS = load_incidents()
INCIDENT_IDS = sorted(INCIDENTS)
# See test_world_state_fault_is_reported_as_unlocalizable.
LOCALIZABLE = [i for i in INCIDENT_IDS if i != "I-005"]
TRIALS = 3


@pytest.fixture(scope="module")
def deterministic_reports() -> dict:
    """One pipeline run per incident with no provider — the fallback path."""
    orchestrator = ForensicOrchestrator(None, trials=TRIALS)
    return {i: orchestrator.investigate(INCIDENTS[i]) for i in INCIDENT_IDS}


def truth_of(incident_id: str) -> str:
    return run_incident(INCIDENTS[incident_id]).run.trace.injection.true_causal_step


class TestPipelineEndToEnd:
    @pytest.mark.parametrize("incident_id", LOCALIZABLE)
    def test_localizes_the_true_cause(self, deterministic_reports, incident_id) -> None:
        assert deterministic_reports[incident_id].root_cause_step == truth_of(incident_id)

    @pytest.mark.parametrize("incident_id", LOCALIZABLE)
    def test_every_causal_claim_cites_an_experiment(
        self, deterministic_reports, incident_id
    ) -> None:
        report = deterministic_reports[incident_id]

        assert report.experiments, "a causal claim with no experiment behind it"
        for artifact in report.experiments:
            assert artifact["artifact_hash"].startswith("sha256:")
            assert "effect_size" in artifact
            assert "baseline_failure_rate" in artifact

        cited = {a["intervention"]["step_id"] for a in report.experiments}
        assert report.root_cause_step in cited

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_report_is_reproducible(self, incident_id) -> None:
        a = ForensicOrchestrator(None, trials=TRIALS).investigate(INCIDENTS[incident_id])
        b = ForensicOrchestrator(None, trials=TRIALS).investigate(INCIDENTS[incident_id])

        assert a.artifact_hash() == b.artifact_hash()

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_report_serializes_to_json(self, deterministic_reports, incident_id) -> None:
        payload = deterministic_reports[incident_id].model_dump(mode="json")

        assert json.loads(json.dumps(payload))

    def test_pipeline_runs_with_the_mock_provider(self) -> None:
        """Mock output is unparseable junk; the pipeline must degrade, not crash."""
        report = ForensicOrchestrator(MockProvider(), trials=TRIALS).investigate(
            INCIDENTS["I-001"]
        )

        assert report.hypothesis_source is HypothesisSource.EXHAUSTIVE_FALLBACK
        assert report.agent_errors, "a failed agent must be recorded, not hidden"
        assert report.root_cause_step == truth_of("I-001")


class TestEvidenceBeatsOpinion:
    def test_a_confident_wrong_agent_cannot_win(self) -> None:
        """The pipeline's central guarantee, end to end.

        The investigator names a wrong step with maximum confidence and the true
        cause with minimum confidence. Measurement must overrule it.
        """
        truth = truth_of("I-001")
        scripted = MockProvider(
            scripted={
                "forensics:investigator": json.dumps(
                    {
                        "hypotheses": [
                            {
                                "suspected_step_id": "s0003",
                                "mechanism": "wrong but stated with total confidence",
                                "confidence": 1.0,
                            },
                            {
                                "suspected_step_id": truth,
                                "mechanism": "right but hedged",
                                "confidence": 0.01,
                            },
                        ]
                    }
                )
            }
        )

        report = ForensicOrchestrator(scripted, trials=TRIALS).investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.AGENT
        assert report.root_cause_step == truth

        by_step = {a["intervention"]["step_id"]: a for a in report.experiments}
        assert by_step["s0003"]["proposer_confidence"] == 1.0
        assert by_step["s0003"]["effect_size"] == 0.0
        assert by_step[truth]["effect_size"] == 1.0

    def test_hypotheses_naming_unreal_steps_are_rejected(self) -> None:
        scripted = MockProvider(
            scripted={
                "forensics:investigator": json.dumps(
                    {"hypotheses": [{"suspected_step_id": "s9999", "mechanism": "invented"}]}
                )
            }
        )

        report = ForensicOrchestrator(scripted, trials=TRIALS).investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.EXHAUSTIVE_FALLBACK
        assert any("no hypothesis named a real step" in e for e in report.agent_errors)


class TestCauseVersusConsequence:
    """D-016: the tie-break should be measurement wherever possible."""

    @pytest.mark.parametrize("incident_id", ["I-001", "I-004"])
    def test_chain_is_resolved_by_measurement_not_heuristic(
        self, deterministic_reports, incident_id
    ) -> None:
        report = deterministic_reports[incident_id]

        assert report.resolved_by_measurement
        assert report.resolution in (
            CauseResolution.DOMINANCE_MEASURED,
            CauseResolution.UNIQUE,
        )

    def test_dominance_evidence_is_recorded_when_used(self, deterministic_reports) -> None:
        report = deterministic_reports["I-001"]

        if report.resolution is CauseResolution.DOMINANCE_MEASURED:
            assert report.dominance_evidence
            assert any(e["normalized"] for e in report.dominance_evidence)

    def test_world_state_fault_is_reported_as_unlocalizable(
        self, deterministic_reports
    ) -> None:
        """I-005 yields no cause, and the pipeline says so instead of guessing.

        Correcting the policy step does not make the run safe — it makes the
        agent request a version the world cannot resolve, so it under-refunds
        instead. No intervention prevents the failure, so there is no evidenced
        cause. Reporting one anyway would be the failure mode this project
        exists to avoid.
        """
        report = deterministic_reports["I-005"]

        assert report.root_cause_step is None
        assert report.resolution is CauseResolution.NONE
        assert report.repair is None

    def test_retry_fault_needs_the_right_intervention_kind(
        self, deterministic_reports
    ) -> None:
        """I-002's cause is a tool_call, unreachable by value replacement."""
        report = deterministic_reports["I-002"]
        trace = run_incident(INCIDENTS["I-002"]).run.trace

        assert trace.step(report.root_cause_step).type is StepType.TOOL_CALL
        chosen = next(
            a
            for a in report.experiments
            if a["intervention"]["step_id"] == report.root_cause_step
        )
        assert chosen["intervention"]["kind"] == "skip_tool_call"


class TestRepairIsMeasuredNotArgued:
    @pytest.mark.parametrize("incident_id", ["I-001", "I-002", "I-003", "I-004"])
    def test_an_acceptable_repair_is_found(self, deterministic_reports, incident_id) -> None:
        report = deterministic_reports[incident_id]

        assert report.repair_accepted
        assert report.repair["prevention_rate"] == 1.0
        assert report.repair["false_block_rate"] == 0.0

    def test_an_uncovered_fault_class_yields_no_accepted_repair(
        self, deterministic_reports
    ) -> None:
        """The guard library has nothing for corrupted refund arithmetic.

        I-007 localizes correctly, but no guardrail in the library prevents it,
        so the best candidate scores prevention 0.00 and is NOT accepted.
        Reporting an ineffective guard as a fix would be worse than reporting
        none — this is measured coverage, not an assumed one.
        """
        report = deterministic_reports["I-007"]

        assert report.root_cause_step is not None
        assert report.repair is not None
        assert report.repair["prevention_rate"] == 0.0
        assert not report.repair_accepted

    def test_blocking_everything_never_outranks_a_clean_repair(self) -> None:
        blocker = evaluate_repair(
            RepairSpec(kind=RepairKind.BLOCK_ALL_REFUNDS),
            scenario_id=INCIDENTS["I-001"].scenario_id,
            seed=1337,
            injection=INCIDENTS["I-001"].injected_failure,
            normal_case_ids=NORMAL_CASES,
            trials=TRIALS,
        )

        assert blocker.prevention_rate == 1.0
        assert blocker.false_block_rate > 0
        assert not blocker.acceptable

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_repair_is_measured_on_both_axes(self, deterministic_reports, incident_id) -> None:
        report = deterministic_reports[incident_id]
        if report.repair is None:
            pytest.skip("no cause localized, so no repair proposed")

        assert report.repair["normal_cases"] == len(NORMAL_CASES)
        assert "prevention_rate" in report.repair
        assert "false_block_rate" in report.repair


class TestAgentsNeverSeeGroundTruth:
    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_redacted_trace_omits_the_answer(self, incident_id) -> None:
        trace = run_incident(INCIDENTS[incident_id]).run.trace
        assert trace.injection is not None

        redacted = redact_for_agent(trace)

        # The causal step id legitimately appears — it is a real step in the
        # trace. What must not appear is anything identifying it AS the cause.
        assert not contains_ground_truth(redacted)
        assert "injection" not in redacted
        assert trace.injection.kind not in json.dumps(redacted)
        assert set(redacted) == {"trace_id", "scenario_id", "agent_version", "outcome", "steps"}

    def test_investigator_is_given_only_the_redacted_trace(self) -> None:
        """Capture what actually reaches the provider."""
        seen: list[str] = []

        class Capturing:
            name = "capturing"

            def complete(self, request):
                seen.append(request.prompt)
                raise AgentOutputError("stop here")

        trace = run_incident(INCIDENTS["I-001"]).run.trace
        try:
            Investigator(Capturing()).investigate(redact_for_agent(trace))
        except AgentOutputError:
            pass

        assert seen
        assert "true_causal_step" not in seen[0]
        assert "stale_policy" not in seen[0]


class TestAgentContracts:
    @pytest.mark.parametrize(
        "name", ["investigator", "counterfactual", "repair", "verifier"]
    )
    def test_prompt_file_exists_and_is_substantive(self, name: str) -> None:
        assert len(load_prompt(name)) > 200

    def test_missing_prompt_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_agent")

    @pytest.mark.parametrize(
        "model", [InvestigationOutput, PlanOutput, RepairOutput]
    )
    def test_malformed_output_raises_rather_than_guessing(self, model) -> None:
        with pytest.raises(AgentOutputError):
            parse_as("the model rambled and produced no JSON", model)

    def test_json_is_recovered_from_fenced_output(self) -> None:
        text = 'Sure!\n```json\n{"hypotheses": []}\n```\nHope that helps.'

        assert extract_json(text) == {"hypotheses": []}

    def test_json_is_recovered_from_a_preamble(self) -> None:
        assert extract_json('Here you go: {"hypotheses": []} done') == {"hypotheses": []}

    def test_schema_violations_are_rejected(self) -> None:
        with pytest.raises(AgentOutputError):
            parse_as('{"hypotheses": [{"confidence": 5.0}]}', InvestigationOutput)

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(AgentOutputError):
            parse_as('{"hypotheses": [], "extra": 1}', InvestigationOutput)


@pytest.mark.live
class TestLiveAgentPath:
    """The pipeline against a real model. Opt-in, billed, needs a key.

    The offline suite proves the *machinery* works; only this proves the agents
    contribute anything. Without it, `hypothesis_source` could be
    `exhaustive_fallback` on every run and the offline tests would still pass.
    """

    @pytest.fixture
    def provider(self):
        import os

        if not os.environ.get("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set")
        from aftermath.llm.gemini import GeminiProvider

        return GeminiProvider(default_model="gemini-3.7-flash")

    def test_agent_hypotheses_are_used_and_localize_correctly(self, provider) -> None:
        orchestrator = ForensicOrchestrator(provider, trials=TRIALS)
        orchestrator._model = "gemini-3.7-flash"

        report = orchestrator.investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.AGENT, report.agent_errors
        assert report.root_cause_step == truth_of("I-001")
        assert report.repair_accepted

    def test_planner_chooses_skip_for_a_duplicated_action(self, provider) -> None:
        """The discriminating case: a retry fault is unreachable by replacement."""
        orchestrator = ForensicOrchestrator(provider, trials=TRIALS)
        orchestrator._model = "gemini-3.7-flash"

        report = orchestrator.investigate(INCIDENTS["I-002"])

        assert report.root_cause_step == truth_of("I-002")
        chosen = next(
            a
            for a in report.experiments
            if a["intervention"]["step_id"] == report.root_cause_step
        )
        assert chosen["intervention"]["kind"] == "skip_tool_call"


class TestProviderFailureResilience:
    """A flaky provider must not end a benchmark run.

    Found during P7: a single transient 5xx from the model aborted a
    20-incident run, because the orchestrator caught only parse failures.
    """

    def test_provider_error_degrades_to_the_deterministic_path(self) -> None:
        from aftermath.llm.base import LLMError

        class Failing:
            name = "failing"

            def complete(self, request):
                raise LLMError("Gemini request failed: ServerError")

        report = ForensicOrchestrator(Failing(), trials=TRIALS).investigate(INCIDENTS["I-001"])

        assert report.hypothesis_source is HypothesisSource.EXHAUSTIVE_FALLBACK
        assert any("ServerError" in e for e in report.agent_errors)
        # The run still produces a correct, evidence-backed answer.
        assert report.root_cause_step == truth_of("I-001")

    def test_intermittent_failure_is_recorded_per_stage(self) -> None:
        from aftermath.llm.base import LLMError

        class FailAfterFirst:
            name = "flaky"

            def __init__(self) -> None:
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                if self.calls > 1:
                    raise LLMError("transient")
                return type("R", (), {"text": json.dumps({"hypotheses": [
                    {"suspected_step_id": truth_of("I-001"), "mechanism": "stale policy"}
                ]})})()

        report = ForensicOrchestrator(FailAfterFirst(), trials=TRIALS).investigate(
            INCIDENTS["I-001"]
        )

        assert report.hypothesis_source is HypothesisSource.AGENT
        assert report.agent_errors, "later stage failures must be recorded"
        assert report.root_cause_step == truth_of("I-001")
