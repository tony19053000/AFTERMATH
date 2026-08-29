"""The MVP monitored agent: a minimal custom loop (D-004).

**What this agent is, honestly.** Its control flow is deterministic policy code,
not model-driven. It calls the LLM provider to narrate its reasoning, and those
calls are recorded as nondeterministic steps so the record/replay machinery is
genuinely exercised — but the *decisions* are Python.

That is deliberate, not a shortcut (D-003). The interesting engineering is in the
forensic and replay layers; a model-driven agent here would make determinism
harder, injection murkier, and causal ground truth ambiguous — undermining the
very thing we are trying to measure. A model-driven agent can be added later
behind the same `CompanyAgent` protocol without touching the pipeline.

Nothing here has a real-world side effect.
"""

from __future__ import annotations

from typing import Any

from aftermath.companyagent.base import AgentRun
from aftermath.companyagent.scenarios import RequestKind, Scenario
from aftermath.companyagent.tools import READ_ONLY_TOOLS, ToolOutcome, call_tool
from aftermath.companyagent.world import World
from aftermath.core.trace import InjectionInfo
from aftermath.llm.base import LLMProvider, LLMRequest
from aftermath.tracing.collector import TraceCollector

AGENT_VERSION = "sim-custops-0.1.0"


class SimpleCustomerOpsAgent:
    """A customer-operations agent over the simulated world."""

    version = AGENT_VERSION

    def __init__(self, provider: LLMProvider | None = None, *, narrate: bool = True) -> None:
        self._provider = provider
        self._narrate = narrate and provider is not None

    # ---- tracing helpers -----------------------------------------------------

    def _think(self, collector: TraceCollector, thought: str, step_tag: str) -> None:
        """Record a reasoning step, optionally narrated by the model.

        The model's text is decorative here; the decision is already made. It is
        still routed through the provider so the recording path is real.
        """
        if not self._narrate:
            collector.reasoning(thought)
            return
        assert self._provider is not None
        request = LLMRequest(
            model="narration",
            prompt=thought,
            tag=f"{self.version}:{step_tag}",
        )
        response = self._provider.complete(request)
        collector.reasoning(
            f"{thought} | {response.text}",
            model=response.model,
            record_id=request.cache_key(),
        )

    def _invoke(
        self,
        collector: TraceCollector,
        world: World,
        tool: str,
        arguments: dict[str, Any],
    ) -> ToolOutcome:
        """Call a tool and record the call, its result, and every mutation.

        Mutations are recorded here, in one place, so no state change can reach
        the world without appearing in the trace.
        """
        call_id = collector.next_call_id()
        snapshot_ref = None if tool in READ_ONLY_TOOLS else f"w{len(collector.steps):04d}"
        collector.tool_call(tool, arguments, call_id, snapshot_ref)
        outcome = call_tool(world, tool, arguments)
        collector.tool_result(tool, call_id, outcome)
        for mutation in outcome.mutations:
            collector.state_mutation(mutation)
        return outcome

    # ---- the loop ------------------------------------------------------------

    def run(
        self,
        scenario: Scenario,
        world: World,
        injection: InjectionInfo | None = None,
    ) -> AgentRun:
        before = world.snapshot()
        collector = TraceCollector(
            trace_id=f"{scenario.scenario_id}-{world.seed}",
            scenario_id=scenario.scenario_id,
            agent_version=self.version,
            seed=world.seed,
        )
        collector.user_input(scenario.user_text)

        if scenario.request_kind is RequestKind.CANCEL:
            self._handle_cancel(collector, world, scenario)
        else:
            self._handle_refund(collector, world, scenario)

        outcome = scenario.judge(world, before)
        trace = collector.seal(outcome, injection=injection)
        return AgentRun(trace=trace, world=world)

    def _handle_cancel(
        self, collector: TraceCollector, world: World, scenario: Scenario
    ) -> None:
        self._think(collector, f"Customer wants to cancel {scenario.order_id}.", "cancel_intent")
        order = self._invoke(collector, world, "get_order", {"order_id": scenario.order_id})
        if order.failed:
            collector.final_output(f"I could not find order {scenario.order_id}.")
            return

        result = self._invoke(collector, world, "cancel_order", {"order_id": scenario.order_id})
        if result.failed:
            collector.final_output(f"I was unable to cancel that order: {result.error}")
            return
        collector.final_output(f"Order {scenario.order_id} has been cancelled.")

    def _handle_refund(
        self, collector: TraceCollector, world: World, scenario: Scenario
    ) -> None:
        self._think(collector, f"Customer wants a refund for {scenario.order_id}.", "refund_intent")

        order = self._invoke(collector, world, "get_order", {"order_id": scenario.order_id})
        if order.failed:
            collector.final_output(f"I could not find order {scenario.order_id}.")
            return

        self._invoke(collector, world, "get_customer", {"customer_id": order.result["customer_id"]})

        policy = self._invoke(collector, world, "get_policy", {"policy_id": "refund"})
        if policy.failed:
            collector.final_output("I could not retrieve the refund policy.")
            return
        policy_version = policy.result["version"]

        quote = self._invoke(
            collector,
            world,
            "calculate_refund",
            {"order_id": scenario.order_id, "policy_version": policy_version},
        )
        if quote.failed:
            collector.final_output("I could not calculate a refund for that order.")
            return

        eligible = bool(quote.result["eligible"])
        amount = int(quote.result["amount_cents"])
        collector.policy_check(
            "refund",
            policy_version,
            passed=eligible,
            detail=(
                f"order age {quote.result['age_days']}d vs window "
                f"{quote.result['window_days']}d"
            ),
        )

        if not eligible or amount <= 0:
            self._think(collector, "Order is outside the refund window.", "deny")
            collector.final_output(
                f"I'm sorry — order {scenario.order_id} falls outside our refund window, "
                "so I can't issue a refund."
            )
            return

        approver: str | None = None
        if quote.result["requires_approval"]:
            self._think(collector, f"Refund of {amount} needs approval.", "escalate")
            approval = self._invoke(
                collector,
                world,
                "request_human_approval",
                {"reason": f"refund {amount} for {scenario.order_id}", "amount_cents": amount},
            )
            granted = bool(approval.result["granted"])
            approver = approval.result["approver"]
            collector.approval_request(
                f"refund {amount} for {scenario.order_id}", granted, approver
            )
            if not granted:
                collector.final_output(
                    "That refund needs supervisor approval, which was not granted."
                )
                return

        self._invoke(
            collector,
            world,
            "issue_simulated_refund",
            {
                "order_id": scenario.order_id,
                "amount_cents": amount,
                "policy_version": policy_version,
                "approved_by": approver,
            },
        )
        collector.final_output(
            f"I've issued a refund of {amount} cents for order {scenario.order_id}."
        )
