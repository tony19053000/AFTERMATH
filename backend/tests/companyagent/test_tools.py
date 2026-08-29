"""Simulated tools: correctness, determinism, and absence of real side effects."""

from __future__ import annotations

import pytest

from aftermath.companyagent.tools import (
    READ_ONLY_TOOLS,
    TOOLS,
    ToolError,
    calculate_refund,
    call_tool,
    cancel_order,
    get_customer,
    get_order,
    get_policy,
    issue_simulated_refund,
    request_human_approval,
)
from aftermath.companyagent.world import OrderStatus, build_world


@pytest.fixture
def world():
    return build_world()


class TestLookups:
    def test_get_customer(self, world) -> None:
        assert get_customer(world, "CUST-1000").result["customer_id"] == "CUST-1000"

    def test_get_customer_unknown_returns_error_not_exception(self, world) -> None:
        outcome = get_customer(world, "CUST-9999")

        assert outcome.failed
        assert "no customer" in outcome.error

    def test_get_order(self, world) -> None:
        assert get_order(world, "ORD-2000").result["order_id"] == "ORD-2000"

    def test_get_order_unknown(self, world) -> None:
        assert get_order(world, "ORD-9999").failed

    def test_get_policy_returns_effective_version(self, world) -> None:
        assert get_policy(world, "refund").result["version"] == "v2"

    def test_get_policy_can_return_a_specific_version(self, world) -> None:
        """The seam a stale-policy injection uses (P3)."""
        assert get_policy(world, "refund", version="v1").result["version"] == "v1"

    def test_get_policy_unknown_version(self, world) -> None:
        assert get_policy(world, "refund", version="v42").failed

    def test_lookups_do_not_mutate(self, world) -> None:
        before = world.state_hash()
        get_customer(world, "CUST-1000")
        get_order(world, "ORD-2000")
        get_policy(world, "refund")
        calculate_refund(world, "ORD-2000", "v2")

        assert world.state_hash() == before

    def test_read_only_set_matches_reality(self, world) -> None:
        for name in READ_ONLY_TOOLS:
            assert TOOLS[name](world, **_minimal_args(name)).mutations == []


def _minimal_args(name: str) -> dict:
    return {
        "get_customer": {"customer_id": "CUST-1000"},
        "get_order": {"order_id": "ORD-2000"},
        "get_policy": {"policy_id": "refund"},
        "calculate_refund": {"order_id": "ORD-2000", "policy_version": "v2"},
    }[name]


class TestCalculateRefund:
    def test_in_window_order_is_eligible(self, world) -> None:
        result = calculate_refund(world, "ORD-2003", "v2").result

        assert result["eligible"] is True
        assert result["amount_cents"] == world.orders["ORD-2003"].amount_cents

    def test_out_of_window_order_is_ineligible(self, world) -> None:
        result = calculate_refund(world, "ORD-2011", "v2").result

        assert result["eligible"] is False
        assert result["amount_cents"] == 0

    def test_stale_policy_widens_the_window(self, world) -> None:
        """The core of the stale-policy incident: v1 permits what v2 forbids."""
        under_v2 = calculate_refund(world, "ORD-2011", "v2").result
        under_v1 = calculate_refund(world, "ORD-2011", "v1").result

        assert under_v2["eligible"] is False
        assert under_v1["eligible"] is True

    def test_premium_tier_gets_a_longer_window(self, world) -> None:
        premium = calculate_refund(world, "ORD-2000", "v2").result

        assert premium["window_days"] > world.policy_version("refund", "v2").refund_window_days

    def test_already_refunded_amount_is_deducted(self, world) -> None:
        issue_simulated_refund(world, "ORD-2003", 5_000, "v2")

        result = calculate_refund(world, "ORD-2003", "v2").result

        assert result["already_refunded_cents"] == 5_000
        assert result["amount_cents"] == world.orders["ORD-2003"].amount_cents - 5_000

    def test_cancelled_order_is_ineligible(self, world) -> None:
        cancel_order(world, "ORD-2008")

        assert calculate_refund(world, "ORD-2008", "v2").result["eligible"] is False

    def test_arithmetic_is_deterministic(self, world) -> None:
        first = calculate_refund(world, "ORD-2003", "v2").result

        assert calculate_refund(build_world(), "ORD-2003", "v2").result == first

    def test_unknown_order(self, world) -> None:
        assert calculate_refund(world, "ORD-9999", "v2").failed


class TestRefundLedger:
    def test_issuing_a_refund_records_a_mutation(self, world) -> None:
        outcome = issue_simulated_refund(world, "ORD-2003", 1_000, "v2")

        assert len(outcome.mutations) == 1
        assert outcome.mutations[0].entity == "refund_ledger"
        assert outcome.mutations[0].after == {"total_refunded_cents": 1_000}

    def test_refund_is_deliberately_not_idempotent(self, world) -> None:
        """Duplicate refunds must be *possible* — that incident class depends on it.

        A tool that silently deduplicated would hide the failure we exist to study.
        """
        issue_simulated_refund(world, "ORD-2003", 1_000, "v2")
        issue_simulated_refund(world, "ORD-2003", 1_000, "v2")

        assert world.total_refunded("ORD-2003") == 2_000
        assert len([r for r in world.refunds if r.order_id == "ORD-2003"]) == 2

    def test_non_positive_amount_rejected(self, world) -> None:
        assert issue_simulated_refund(world, "ORD-2003", 0, "v2").failed
        assert issue_simulated_refund(world, "ORD-2003", -100, "v2").failed

    def test_unknown_order_rejected(self, world) -> None:
        assert issue_simulated_refund(world, "ORD-9999", 100, "v2").failed

    def test_approver_is_recorded(self, world) -> None:
        issue_simulated_refund(world, "ORD-2003", 100, "v2", approved_by="sim-supervisor")

        assert world.refunds[0].approved_by == "sim-supervisor"


class TestCancellation:
    def test_cancel_pending_order(self, world) -> None:
        outcome = cancel_order(world, "ORD-2008")

        assert world.orders["ORD-2008"].status == OrderStatus.CANCELLED
        assert outcome.mutations[0].before == {"status": "pending"}

    def test_cannot_cancel_twice(self, world) -> None:
        cancel_order(world, "ORD-2008")

        assert "already cancelled" in cancel_order(world, "ORD-2008").error

    def test_cannot_cancel_delivered_order(self, world) -> None:
        assert "delivered" in cancel_order(world, "ORD-2000").error

    def test_failed_cancel_mutates_nothing(self, world) -> None:
        before = world.state_hash()
        cancel_order(world, "ORD-2000")

        assert world.state_hash() == before


class TestApproval:
    def test_approval_granted_within_ceiling(self, world) -> None:
        result = request_human_approval(world, "refund", 10_000).result

        assert result["granted"] is True
        assert result["approver"] == "sim-supervisor"

    def test_approval_denied_above_ceiling(self, world) -> None:
        result = request_human_approval(world, "refund", 100_000).result

        assert result["granted"] is False
        assert result["approver"] is None

    def test_approval_is_counted_as_a_mutation(self, world) -> None:
        outcome = request_human_approval(world, "refund", 1_000)

        assert world.approvals_requested == 1
        assert outcome.mutations[0].entity_id == "approvals_requested"


class TestDispatch:
    def test_unknown_tool_raises(self, world) -> None:
        with pytest.raises(ToolError, match="unknown tool"):
            call_tool(world, "delete_production_database", {})

    def test_bad_arguments_raise(self, world) -> None:
        with pytest.raises(ToolError, match="bad arguments"):
            call_tool(world, "get_order", {"wrong_kwarg": 1})

    def test_exactly_seven_tools(self) -> None:
        assert len(TOOLS) == 7

    def test_no_tool_performs_a_real_side_effect(self) -> None:
        """Standing security rule: the simulated agent touches nothing real."""
        import inspect

        from aftermath.companyagent import tools as tools_module

        source = inspect.getsource(tools_module)
        for forbidden in ("requests.", "httpx.", "urlopen", "smtplib", "subprocess", "socket."):
            assert forbidden not in source, f"tool module references {forbidden}"
