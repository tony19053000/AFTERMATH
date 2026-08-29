"""Fault injection and the incident benchmark.

P3 acceptance:
* each incident reproduces its failure under its seed at a stable, documented rate,
* ground truth is written by the injector and **never** by a model,
* clean runs of the same scenarios still pass,
* incidents load from `data/incidents/` and validate against the schema.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aftermath.companyagent.scenarios import ORACLES, SCENARIOS
from aftermath.core.trace import OutcomeStatus, StepType
from aftermath.injection import injector as injector_module
from aftermath.injection.incidents import (
    INCIDENT_DIR,
    IncidentDefinition,
    load_incident,
    load_incidents,
)
from aftermath.injection.injector import Injector, NullInjector
from aftermath.injection.runner import NORMAL_CASES, failure_rate, run_clean, run_incident
from aftermath.injection.spec import InjectionKind, InjectionLayer, InjectionSpec

INCIDENTS = load_incidents()
INCIDENT_IDS = sorted(INCIDENTS)

# Documented expected failure rate. The current agent is fully deterministic, so
# every trial is identical and the rate is exactly 1.0. It is *measured* rather
# than assumed so the number stays honest once P4 introduces resampled replay.
EXPECTED_FAILURE_RATE = 1.0


class TestIncidentLoading:
    def test_incidents_exist(self) -> None:
        assert len(INCIDENTS) >= 3, "P3 requires at least 3 incidents"

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_definition_validates(self, incident_id: str) -> None:
        assert isinstance(INCIDENTS[incident_id], IncidentDefinition)

    def test_every_definition_file_parses(self) -> None:
        files = sorted(INCIDENT_DIR.glob("*.json"))

        assert files
        for path in files:
            assert load_incident(path).incident_id

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_references_a_real_scenario_and_oracle(self, incident_id: str) -> None:
        incident = INCIDENTS[incident_id]

        assert incident.scenario_id in SCENARIOS
        assert incident.failing_oracle in ORACLES

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        payload = json.loads(sorted(INCIDENT_DIR.glob("*.json"))[0].read_text())
        (tmp_path / "a.json").write_text(json.dumps(payload))
        (tmp_path / "b.json").write_text(json.dumps(payload))

        with pytest.raises(ValueError, match="duplicate incident_id"):
            load_incidents(tmp_path)

    def test_malformed_json_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{not json")

        with pytest.raises(ValueError, match="not valid JSON"):
            load_incident(tmp_path / "bad.json")

    def test_unknown_field_is_rejected(self, tmp_path: Path) -> None:
        payload = json.loads(sorted(INCIDENT_DIR.glob("*.json"))[0].read_text())
        payload["surprise"] = 1
        (tmp_path / "x.json").write_text(json.dumps(payload))

        with pytest.raises(ValidationError):
            load_incident(tmp_path / "x.json")

    def test_definitions_do_not_hard_code_a_causal_step(self) -> None:
        """`true_causal_step` is produced by running, not asserted by hand.

        A hand-written causal step would be a causal claim with no experiment
        behind it — the exact habit this project exists to replace.
        """
        assert "true_causal_step" not in IncidentDefinition.model_fields
        for path in INCIDENT_DIR.glob("*.json"):
            assert "true_causal_step" not in path.read_text()


class TestIncidentsReproduce:
    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_incident_fails_its_declared_oracle(self, incident_id: str) -> None:
        incident = INCIDENTS[incident_id]
        result = run_incident(incident)

        assert result.failed, f"{incident_id} did not fail: {result.run.trace.outcome.detail}"
        assert result.run.trace.outcome.oracle == incident.failing_oracle, (
            "incident failed for a different reason than declared — "
            "the benchmark would be measuring the wrong thing"
        )

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_failure_rate_is_stable_and_documented(self, incident_id: str) -> None:
        assert failure_rate(INCIDENTS[incident_id], trials=5) == EXPECTED_FAILURE_RATE

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_repeated_runs_are_identical(self, incident_id: str) -> None:
        incident = INCIDENTS[incident_id]

        first = run_incident(incident).run.trace
        second = run_incident(incident).run.trace

        assert first.content_hash() == second.content_hash()

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_injection_actually_fired(self, incident_id: str) -> None:
        assert run_incident(INCIDENTS[incident_id]).injector_fired

    def test_an_injection_that_never_fires_raises(self) -> None:
        """A fault that never applied must not be reported as a reproduced incident."""
        incident = INCIDENTS[INCIDENT_IDS[0]].model_copy(
            update={
                "injected_failure": InjectionSpec(
                    kind=InjectionKind.STALE_POLICY,
                    layer=InjectionLayer.TOOL_RESULT,
                    target_tool="cancel_order",  # never called in a refund scenario
                )
            }
        )

        with pytest.raises(RuntimeError, match="never fired"):
            run_incident(incident)

    def test_context_layer_is_declared_but_unimplemented(self) -> None:
        """Taxonomy exists; no kind implements it. A spec using it fails loudly."""
        incident = INCIDENTS[INCIDENT_IDS[0]].model_copy(
            update={
                "injected_failure": InjectionSpec(
                    kind=InjectionKind.STALE_POLICY,
                    layer=InjectionLayer.CONTEXT,
                    target_tool="get_policy",
                )
            }
        )

        with pytest.raises(RuntimeError, match="never fired"):
            run_incident(incident)


class TestGroundTruthProvenance:
    """D-002: ground truth comes from the injector, never from a model."""

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_causal_step_is_recorded_and_real(self, incident_id: str) -> None:
        result = run_incident(INCIDENTS[incident_id])
        trace = result.run.trace

        assert trace.injection is not None
        assert result.true_causal_step is not None
        # Must name a step that actually exists — the schema enforces it too.
        assert trace.step(result.true_causal_step)

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_causal_step_precedes_the_final_output(self, incident_id: str) -> None:
        trace = run_incident(INCIDENTS[incident_id]).run.trace
        causal_index = [s.step_id for s in trace.steps].index(
            trace.injection.true_causal_step
        )

        assert causal_index < len(trace.steps) - 1

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_causal_step_is_the_perturbed_tool(self, incident_id: str) -> None:
        incident = INCIDENTS[incident_id]
        trace = run_incident(incident).run.trace
        step = trace.step(trace.injection.true_causal_step)

        assert step.type in (StepType.TOOL_CALL, StepType.TOOL_RESULT)
        assert step.tool == incident.injected_failure.target_tool

    def test_injector_module_makes_no_llm_call(self) -> None:
        """The injector is deterministic Python. Ground truth is never model output."""
        source = inspect.getsource(injector_module)

        assert "aftermath.llm" not in source
        assert "complete(" not in source

    def test_ground_truth_source_is_the_injector(self) -> None:
        for incident in INCIDENTS.values():
            assert incident.ground_truth_source == "fault_injector"

    def test_agent_never_receives_the_ground_truth(self) -> None:
        """The agent must not be able to see, or shape, the answer being measured."""
        from aftermath.companyagent import simple

        source = inspect.getsource(simple.SimpleCustomerOpsAgent)

        assert "true_causal_step" not in source

    def test_ground_truth_unavailable_before_firing(self) -> None:
        fresh = Injector(
            InjectionSpec(kind=InjectionKind.STALE_POLICY, layer=InjectionLayer.TOOL_RESULT)
        )

        assert not fresh.fired
        with pytest.raises(RuntimeError, match="no ground truth exists"):
            fresh.ground_truth()


class TestCleanRunsStillPass:
    """The injection machinery must not disturb an uninjected run."""

    @pytest.mark.parametrize("scenario_id", NORMAL_CASES)
    def test_clean_scenario_passes(self, scenario_id: str) -> None:
        run = run_clean(scenario_id)

        assert run.trace.outcome.status is OutcomeStatus.PASS, run.trace.outcome.detail
        assert run.trace.injection is None

    def test_normal_cases_cover_every_scenario(self) -> None:
        assert set(NORMAL_CASES) == set(SCENARIOS)

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_injected_and_clean_runs_of_the_same_scenario_differ(
        self, incident_id: str
    ) -> None:
        """The differential is the whole point: same scenario, one fault, opposite verdict."""
        incident = INCIDENTS[incident_id]

        injected = run_incident(incident).run
        clean = run_clean(incident.scenario_id)

        assert clean.trace.outcome.status is OutcomeStatus.PASS
        assert injected.trace.outcome.status is OutcomeStatus.FAIL
        assert injected.trace.content_hash() != clean.trace.content_hash()

    def test_null_injector_leaves_a_run_untouched(self) -> None:
        from aftermath.companyagent.scenarios import get_scenario
        from aftermath.companyagent.simple import SimpleCustomerOpsAgent
        from aftermath.companyagent.world import build_world

        plain = SimpleCustomerOpsAgent(None).run(get_scenario("refund_in_window"), build_world())
        nulled = SimpleCustomerOpsAgent(None, injector=NullInjector()).run(
            get_scenario("refund_in_window"), build_world()
        )

        assert plain.trace.content_hash() == nulled.trace.content_hash()


class TestInjectionMechanics:
    def test_occurrence_targets_a_specific_call(self) -> None:
        """Hitting every matching call would make the causal step ambiguous."""
        spec = InjectionSpec(
            kind=InjectionKind.STALE_POLICY,
            layer=InjectionLayer.TOOL_RESULT,
            target_tool="get_policy",
            occurrence=2,
        )
        injector = Injector(spec)

        assert injector._should_fire("get_policy") is False  # 1st call
        assert injector._should_fire("get_policy") is True  # 2nd call

    def test_injection_fires_only_once(self) -> None:
        result = run_incident(INCIDENTS["I-001"])
        trace = result.run.trace

        policy_results = [
            s
            for s in trace.steps
            if s.type is StepType.TOOL_RESULT and s.tool == "get_policy"
        ]
        assert len(policy_results) == 1
        assert trace.injection.true_causal_step == policy_results[0].step_id

    def test_retry_fault_appends_a_real_duplicate_call(self) -> None:
        trace = run_incident(INCIDENTS["I-002"]).run.trace
        refund_calls = [
            s
            for s in trace.steps
            if s.type is StepType.TOOL_CALL and s.tool == "issue_simulated_refund"
        ]

        assert len(refund_calls) == 2
        # The duplicated call is the cause, not the original.
        assert trace.injection.true_causal_step == refund_calls[1].step_id

    def test_world_state_fault_leaves_tools_honest(self) -> None:
        """In I-005 the tool is correct; the environment is wrong."""
        result = run_incident(INCIDENTS["I-005"])

        assert [p.version for p in result.run.world.policies] == ["v1"]
        # The tool truthfully reported the only policy that exists in that world.
        step = result.run.trace.step(result.true_causal_step)
        assert step.result["version"] == "v1"

    def test_tool_result_and_world_state_faults_are_distinguishable(self) -> None:
        """I-001 and I-005 produce the same outcome by different mechanisms.

        Both over-refund ORD-2011, but one corrupts a tool result while the other
        rolls back the world. P4/P5 must be able to tell them apart, so they are
        deliberately kept as separate incidents.
        """
        tool_fault = run_incident(INCIDENTS["I-001"]).run
        world_fault = run_incident(INCIDENTS["I-005"]).run

        assert tool_fault.trace.outcome.status is world_fault.trace.outcome.status
        assert [p.version for p in tool_fault.world.policies] == ["v1", "v2"]
        assert [p.version for p in world_fault.world.policies] == ["v1"]

    def test_severity_is_recorded_on_the_trace(self) -> None:
        trace = run_incident(INCIDENTS["I-002"]).run.trace

        assert trace.injection.severity.value == "critical"

    @pytest.mark.parametrize("incident_id", INCIDENT_IDS)
    def test_injection_params_record_what_changed(self, incident_id: str) -> None:
        trace = run_incident(INCIDENTS[incident_id]).run.trace

        assert trace.injection.params, "injection recorded no detail about what it changed"
