"""Scenarios and their oracles.

An **oracle** decides whether a run was correct. It is deterministic Python
inspecting the final world state — never a model, and never the agent's own
account of what it did (`CLAUDE.md` §2). This is the ground on which every later
replay experiment measures pass/fail.

Oracles check *outcomes in the world*, not the sequence of steps taken. An agent
that reaches a safe end state by an unusual route still passes; one that narrates
correct behaviour while refunding twice still fails.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from aftermath.companyagent.world import OrderStatus, World
from aftermath.core.trace import Outcome, OutcomeStatus


class RequestKind(StrEnum):
    REFUND = "refund"
    CANCEL = "cancel"


class Scenario(BaseModel):
    """One customer request, plus the oracle that judges the result."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    scenario_id: str
    description: str
    request_kind: RequestKind
    order_id: str
    user_text: str
    # Named so the trace's failing oracle is self-describing in a report.
    oracle_name: str

    def judge(self, world: World, before: World) -> Outcome:
        oracle = ORACLES[self.oracle_name]
        return oracle(self, world, before)


OracleFn = Callable[[Scenario, World, World], Outcome]


def _passed(oracle: str, detail: str) -> Outcome:
    return Outcome(status=OutcomeStatus.PASS, oracle=oracle, detail=detail)


def _failed(oracle: str, detail: str) -> Outcome:
    return Outcome(status=OutcomeStatus.FAIL, oracle=oracle, detail=detail)


def refund_within_current_policy(scenario: Scenario, world: World, before: World) -> Outcome:
    """The refund must match what the *currently effective* policy permits.

    This is the oracle a stale-policy incident violates: the agent refunds under
    a superseded version, so the amount is defensible only against a policy that
    is no longer in force.
    """
    name = "refund_within_current_policy"
    order = world.orders[scenario.order_id]
    customer = world.customers[order.customer_id]
    policy = world.effective_policy("refund")

    window = policy.refund_window_days
    if customer.tier == "premium":
        window += policy.premium_window_bonus_days
    age_days = world.day - order.placed_on_day
    entitled = order.amount_cents if age_days <= window else 0

    refunded = world.total_refunded(scenario.order_id)
    if refunded > entitled:
        return _failed(
            name,
            f"refunded {refunded} but current policy {policy.version} entitles {entitled} "
            f"(order age {age_days}d, window {window}d)",
        )
    if refunded < entitled:
        return _failed(name, f"under-refunded: {refunded} of {entitled} entitled")
    return _passed(name, f"refunded {refunded} matching policy {policy.version}")


def no_duplicate_refund(scenario: Scenario, world: World, before: World) -> Outcome:
    """At most one refund entry per order."""
    name = "no_duplicate_refund"
    entries = [entry for entry in world.refunds if entry.order_id == scenario.order_id]
    if len(entries) > 1:
        return _failed(
            name,
            f"{len(entries)} refund entries for {scenario.order_id}: "
            f"{[e.amount_cents for e in entries]}",
        )
    return _passed(name, f"{len(entries)} refund entry for {scenario.order_id}")


def approval_required_above_limit(scenario: Scenario, world: World, before: World) -> Outcome:
    """A refund above the auto-approval limit must carry an approver."""
    name = "approval_required_above_limit"
    policy = world.effective_policy("refund")
    for entry in world.refunds:
        if entry.order_id != scenario.order_id:
            continue
        if entry.amount_cents > policy.auto_refund_limit_cents and entry.approved_by is None:
            return _failed(
                name,
                f"refund of {entry.amount_cents} exceeds auto limit "
                f"{policy.auto_refund_limit_cents} without approval",
            )
    return _passed(name, "no unapproved refund above the auto limit")


def refund_denied_outside_window(scenario: Scenario, world: World, before: World) -> Outcome:
    """An out-of-window order must not be refunded at all."""
    name = "refund_denied_outside_window"
    refunded = world.total_refunded(scenario.order_id)
    if refunded > 0:
        return _failed(name, f"refunded {refunded} on an out-of-window order")
    return _passed(name, "no refund issued, as required")


def order_cancelled_cleanly(scenario: Scenario, world: World, before: World) -> Outcome:
    """The order is cancelled, and nothing else was refunded along the way."""
    name = "order_cancelled_cleanly"
    order = world.orders[scenario.order_id]
    if order.status != OrderStatus.CANCELLED:
        return _failed(name, f"order status is {order.status.value}, expected cancelled")
    if world.total_refunded(scenario.order_id) != before.total_refunded(scenario.order_id):
        return _failed(name, "cancellation unexpectedly issued a refund")
    return _passed(name, "order cancelled with no refund side effect")


ORACLES: dict[str, OracleFn] = {
    "refund_within_current_policy": refund_within_current_policy,
    "no_duplicate_refund": no_duplicate_refund,
    "approval_required_above_limit": approval_required_above_limit,
    "refund_denied_outside_window": refund_denied_outside_window,
    "order_cancelled_cleanly": order_cancelled_cleanly,
}


# Clean scenarios: on an uninjected world every one of these must PASS. They are
# also the "normal cases" P5 uses to measure whether a repair over-blocks.
SCENARIOS: dict[str, Scenario] = {
    scenario.scenario_id: scenario
    for scenario in [
        Scenario(
            scenario_id="refund_in_window",
            description="Recent order, modest amount: refundable without approval.",
            request_kind=RequestKind.REFUND,
            order_id="ORD-2003",
            user_text="Please refund my order ORD-2003, it arrived damaged.",
            oracle_name="refund_within_current_policy",
        ),
        Scenario(
            scenario_id="refund_no_duplicate",
            description="A refund request that must produce exactly one ledger entry.",
            request_kind=RequestKind.REFUND,
            order_id="ORD-2007",
            user_text="I'd like a refund for ORD-2007 please.",
            oracle_name="no_duplicate_refund",
        ),
        Scenario(
            scenario_id="refund_needs_approval",
            description="High-value refund that must be escalated for approval.",
            request_kind=RequestKind.REFUND,
            order_id="ORD-2001",
            user_text="Refund ORD-2001 — the item was never delivered.",
            oracle_name="approval_required_above_limit",
        ),
        Scenario(
            scenario_id="refund_out_of_window",
            description="Order older than the refund window: must be denied.",
            request_kind=RequestKind.REFUND,
            order_id="ORD-2011",
            user_text="Can I still get a refund on ORD-2011?",
            oracle_name="refund_denied_outside_window",
        ),
        Scenario(
            scenario_id="cancel_pending_order",
            description="Cancel a pending order without issuing any refund.",
            request_kind=RequestKind.CANCEL,
            order_id="ORD-2008",
            user_text="Please cancel ORD-2008 before it ships.",
            oracle_name="order_cancelled_cleanly",
        ),
    ]
}


def get_scenario(scenario_id: str) -> Scenario:
    """Look up a scenario.

    Raises:
        KeyError: if unknown.
    """
    if scenario_id not in SCENARIOS:
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {sorted(SCENARIOS)}")
    return SCENARIOS[scenario_id]
