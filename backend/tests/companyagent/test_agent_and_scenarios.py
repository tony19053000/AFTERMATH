"""Agent runs, trace completeness, and scenario oracles.

P2 acceptance, in order:
* a fixed-seed scenario run produces a valid trace,
* every tool call and state mutation appears in the trace with a stable id,
* clean scenarios pass their oracles,
* swapping the agent implementation touches only `companyagent/`.
"""

from __future__ import annotations

import pytest

from aftermath.companyagent.base import AgentRun, CompanyAgent
from aftermath.companyagent.scenarios import ORACLES, SCENARIOS, get_scenario
from aftermath.companyagent.simple import SimpleCustomerOpsAgent
from aftermath.companyagent.world import World, build_world
from aftermath.core.trace import (
    OutcomeStatus,
    StepType,
    Trace,
    format_step_id,
)
from aftermath.llm.mock import MockProvider


def run_scenario(scenario_id: str, seed: int = 1337, narrate: bool = True) -> AgentRun:
    agent = SimpleCustomerOpsAgent(MockProvider(), narrate=narrate)
    return agent.run(get_scenario(scenario_id), build_world(seed))


ALL_SCENARIOS = sorted(SCENARIOS)


class TestCleanScenariosPassTheirOracles:
    """On an uninjected world, every clean scenario must pass."""

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_scenario_passes(self, scenario_id: str) -> None:
        run = run_scenario(scenario_id)

        assert run.trace.outcome.status is OutcomeStatus.PASS, run.trace.outcome.detail

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_oracle_name_is_recorded(self, scenario_id: str) -> None:
        run = run_scenario(scenario_id)

        assert run.trace.outcome.oracle == get_scenario(scenario_id).oracle_name

    def test_every_scenario_has_a_registered_oracle(self) -> None:
        for scenario in SCENARIOS.values():
            assert scenario.oracle_name in ORACLES

    def test_scenarios_cover_refund_and_cancel(self) -> None:
        kinds = {s.request_kind.value for s in SCENARIOS.values()}

        assert kinds == {"refund", "cancel"}

    def test_unknown_scenario_raises(self) -> None:
        with pytest.raises(KeyError, match="unknown scenario"):
            get_scenario("does_not_exist")


class TestTraceValidity:
    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_trace_is_valid_and_round_trips(self, scenario_id: str) -> None:
        trace = run_scenario(scenario_id).trace

        restored = Trace.from_jsonl(trace.to_jsonl())

        assert restored == trace
        assert restored.content_hash() == trace.content_hash()

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_step_ids_are_ordinal_and_stable(self, scenario_id: str) -> None:
        trace = run_scenario(scenario_id).trace

        assert [s.step_id for s in trace.steps] == [
            format_step_id(i) for i in range(len(trace.steps))
        ]

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_trace_begins_with_input_and_ends_with_output(self, scenario_id: str) -> None:
        trace = run_scenario(scenario_id).trace

        assert trace.steps[0].type is StepType.USER_INPUT
        assert trace.steps[-1].type is StepType.FINAL_OUTPUT

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_every_tool_call_has_a_matching_result(self, scenario_id: str) -> None:
        trace = run_scenario(scenario_id).trace
        calls = {s.call_id for s in trace.steps if s.type is StepType.TOOL_CALL}
        results = {s.call_id for s in trace.steps if s.type is StepType.TOOL_RESULT}

        assert calls == results
        assert calls, "scenario made no tool calls at all"


class TestTraceCompleteness:
    """No state change may reach the world without appearing in the trace."""

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_mutations_are_all_traced(self, scenario_id: str) -> None:
        run = run_scenario(scenario_id)
        traced = [s for s in run.trace.steps if s.type is StepType.STATE_MUTATION]

        # Every observable change in the end world must have a mutation step.
        clean = build_world(run.trace.seed)
        expected = 0
        expected += len(run.world.refunds) - len(clean.refunds)
        expected += len(run.world.cancellations) - len(clean.cancellations)
        expected += run.world.approvals_requested - clean.approvals_requested

        assert len(traced) == expected

    def test_a_refund_produces_a_ledger_mutation_step(self) -> None:
        run = run_scenario("refund_in_window")
        entities = {
            s.entity for s in run.trace.steps if s.type is StepType.STATE_MUTATION
        }

        assert "refund_ledger" in entities

    def test_a_cancellation_produces_an_order_mutation_step(self) -> None:
        run = run_scenario("cancel_pending_order")
        mutations = [s for s in run.trace.steps if s.type is StepType.STATE_MUTATION]

        assert any(s.entity == "order" and s.after == {"status": "cancelled"} for s in mutations)

    def test_read_only_scenario_records_no_mutation(self) -> None:
        """A denied refund changes nothing, so it must trace no mutation."""
        run = run_scenario("refund_out_of_window")

        assert not [s for s in run.trace.steps if s.type is StepType.STATE_MUTATION]
        assert run.world.state_hash() == build_world(run.trace.seed).state_hash()

    def test_write_tool_calls_carry_a_snapshot_ref(self) -> None:
        """Replay branches from snapshots, so state-changing calls must reference one."""
        run = run_scenario("refund_in_window")
        writes = [
            s
            for s in run.trace.steps
            if s.type is StepType.TOOL_CALL and s.tool == "issue_simulated_refund"
        ]

        assert writes and all(s.world_snapshot_ref is not None for s in writes)


class TestRunDeterminism:
    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_same_seed_produces_identical_trace(self, scenario_id: str) -> None:
        first = run_scenario(scenario_id)
        second = run_scenario(scenario_id)

        assert first.trace.content_hash() == second.trace.content_hash()
        assert first.trace.to_jsonl() == second.trace.to_jsonl()

    @pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
    def test_same_seed_produces_identical_end_world(self, scenario_id: str) -> None:
        assert run_scenario(scenario_id).world.state_hash() == (
            run_scenario(scenario_id).world.state_hash()
        )

    def test_different_seed_changes_the_world(self) -> None:
        assert (
            run_scenario("refund_in_window", seed=1337).world.state_hash()
            != run_scenario("refund_in_window", seed=4242).world.state_hash()
        )

    def test_narration_is_recorded_as_nondeterministic(self) -> None:
        """Model calls must be marked so replay reuses the record instead of re-sampling."""
        trace = run_scenario("refund_in_window", narrate=True).trace
        reasoning = [s for s in trace.steps if s.type is StepType.AGENT_REASONING]

        assert reasoning
        assert all(s.nondeterminism is not None for s in reasoning)
        assert all(s.nondeterminism.source.value == "llm" for s in reasoning)

    def test_agent_runs_without_a_provider(self) -> None:
        """Control flow is deterministic Python; the model is narration only."""
        narrated = run_scenario("refund_in_window", narrate=True)
        silent = SimpleCustomerOpsAgent(None).run(
            get_scenario("refund_in_window"), build_world()
        )

        assert silent.trace.outcome.status is narrated.trace.outcome.status
        assert silent.world.state_hash() == narrated.world.state_hash()


class TestAdapterBoundary:
    """Swapping the monitored agent must touch only `companyagent/`."""

    def test_simple_agent_satisfies_the_protocol(self) -> None:
        assert isinstance(SimpleCustomerOpsAgent(MockProvider()), CompanyAgent)

    def test_an_alternative_agent_implementation_is_accepted(self) -> None:
        """A different agent, written here, needs no change anywhere else."""

        class MinimalAgent:
            version = "alt-agent-0.1.0"

            def run(self, scenario, world: World, injection=None) -> AgentRun:
                from aftermath.tracing.collector import TraceCollector

                before = world.snapshot()
                collector = TraceCollector(
                    trace_id="alt-1",
                    scenario_id=scenario.scenario_id,
                    agent_version=self.version,
                    seed=world.seed,
                )
                collector.user_input(scenario.user_text)
                collector.final_output("I cannot help with that.")
                return AgentRun(
                    trace=collector.seal(scenario.judge(world, before)), world=world
                )

        agent = MinimalAgent()
        run = agent.run(get_scenario("refund_out_of_window"), build_world())

        assert isinstance(agent, CompanyAgent)
        assert run.trace.agent_version == "alt-agent-0.1.0"
        # A do-nothing agent still passes a "deny the refund" oracle, and the
        # trace layer accepts it without knowing anything about the agent.
        assert run.trace.outcome.status is OutcomeStatus.PASS

    def test_no_adk_dependency(self) -> None:
        """D-004: the MVP agent is a custom loop; ADK is not a dependency."""
        import inspect

        from aftermath.companyagent import simple

        assert "adk" not in inspect.getsource(simple).lower()

    def test_agent_version_is_recorded_in_the_trace(self) -> None:
        run = run_scenario("refund_in_window")

        assert run.trace.agent_version == SimpleCustomerOpsAgent.version

    def test_injection_is_recorded_verbatim_and_not_interpreted(self) -> None:
        """Ground truth passes through the agent untouched (D-002), ready for P3."""
        from aftermath.core.trace import InjectionInfo, Severity

        injection = InjectionInfo(
            kind="stale_policy",
            params={"served_version": "v1"},
            true_causal_step=format_step_id(3),
            severity=Severity.HIGH,
        )
        agent = SimpleCustomerOpsAgent(MockProvider())
        clean = agent.run(get_scenario("refund_in_window"), build_world())
        marked = agent.run(get_scenario("refund_in_window"), build_world(), injection)

        assert marked.trace.injection == injection
        # Recording ground truth must not change what the agent actually did.
        assert [s.step_id for s in marked.trace.steps] == [s.step_id for s in clean.trace.steps]
        assert marked.world.state_hash() == clean.world.state_hash()


class TestOracleIndependence:
    """Oracles judge world state, not the agent's account of itself."""

    def test_oracle_ignores_agent_narration(self) -> None:
        run = run_scenario("refund_out_of_window")
        final = run.trace.steps[-1]

        assert "can't issue a refund" in final.text
        # The oracle reached the same conclusion from the ledger, independently.
        assert run.world.total_refunded("ORD-2011") == 0

    def test_oracle_catches_a_duplicate_refund(self) -> None:
        """Negative control: the oracle must fail when the world is actually wrong."""
        from aftermath.companyagent.tools import issue_simulated_refund

        run = run_scenario("refund_no_duplicate")
        assert run.trace.outcome.status is OutcomeStatus.PASS

        issue_simulated_refund(run.world, "ORD-2007", 1_000, "v2")
        verdict = get_scenario("refund_no_duplicate").judge(
            run.world, build_world(run.trace.seed)
        )

        assert verdict.status is OutcomeStatus.FAIL
        assert "2 refund entries" in verdict.detail

    def test_oracle_catches_an_unapproved_large_refund(self) -> None:
        from aftermath.companyagent.tools import issue_simulated_refund

        world = build_world()
        issue_simulated_refund(world, "ORD-2001", 30_700, "v2", approved_by=None)
        verdict = get_scenario("refund_needs_approval").judge(world, build_world())

        assert verdict.status is OutcomeStatus.FAIL
        assert "without approval" in verdict.detail

    def test_oracle_catches_an_over_refund_under_stale_policy(self) -> None:
        """The failure mode P3 will inject: refunding what only v1 permitted."""
        from aftermath.companyagent.tools import issue_simulated_refund

        world = build_world()
        issue_simulated_refund(world, "ORD-2011", world.orders["ORD-2011"].amount_cents, "v1")
        verdict = ORACLES["refund_within_current_policy"](
            SCENARIOS["refund_out_of_window"], world, build_world()
        )

        assert verdict.status is OutcomeStatus.FAIL
        assert "entitles 0" in verdict.detail
