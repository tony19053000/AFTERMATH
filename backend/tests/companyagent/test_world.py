"""Simulated world: seeded determinism and policy versioning.

P2 acceptance: the same seed reproduces the same world state and tool results.
"""

from __future__ import annotations

import pytest

from aftermath.companyagent.world import (
    CustomerTier,
    OrderStatus,
    World,
    build_world,
    describe_world,
)


class TestDeterminism:
    def test_same_seed_produces_identical_world(self) -> None:
        assert build_world(1337).state_hash() == build_world(1337).state_hash()

    def test_different_seeds_produce_different_worlds(self) -> None:
        assert build_world(1337).state_hash() != build_world(9999).state_hash()

    def test_determinism_holds_across_many_seeds(self) -> None:
        for seed in (0, 1, 42, 1337, 2**31 - 1):
            assert build_world(seed).state_hash() == build_world(seed).state_hash()

    def test_world_has_no_wall_clock_dependency(self) -> None:
        """Time is an integer day. A world that read the real clock could not replay."""
        world = build_world()
        payload = world.model_dump(mode="json")

        assert isinstance(payload["day"], int)
        assert "timestamp" not in payload and "now" not in payload

    def test_snapshot_is_independent(self) -> None:
        world = build_world()
        snapshot = world.snapshot()

        world.orders["ORD-2000"].status = OrderStatus.CANCELLED
        world.refunds.clear()

        assert snapshot.orders["ORD-2000"].status != OrderStatus.CANCELLED
        assert snapshot.state_hash() != world.state_hash()

    def test_snapshot_round_trips_to_same_hash(self) -> None:
        world = build_world()

        assert world.snapshot().state_hash() == world.state_hash()


class TestPolicyVersioning:
    def test_effective_policy_is_the_latest_in_force(self) -> None:
        world = build_world(day=120)

        assert world.effective_policy("refund").version == "v2"

    def test_earlier_day_selects_earlier_version(self) -> None:
        world = build_world(day=50)

        assert world.effective_policy("refund").version == "v1"

    def test_superseded_version_remains_retrievable(self) -> None:
        """A stale-policy injection needs to be able to serve v1 on purpose (P3)."""
        world = build_world(day=120)

        assert world.policy_version("refund", "v1").refund_window_days == 90

    def test_v2_is_stricter_than_v1(self) -> None:
        """The gap between versions is what makes staleness observable."""
        world = build_world()
        v1 = world.policy_version("refund", "v1")
        v2 = world.policy_version("refund", "v2")

        assert v2.refund_window_days < v1.refund_window_days
        assert v2.auto_refund_limit_cents < v1.auto_refund_limit_cents

    def test_unknown_policy_raises(self) -> None:
        with pytest.raises(KeyError, match="no effective version"):
            build_world().effective_policy("nonexistent")

    def test_unknown_version_raises(self) -> None:
        with pytest.raises(KeyError, match="no version"):
            build_world().policy_version("refund", "v99")

    def test_no_policy_effective_before_any_version(self) -> None:
        world = build_world(day=120)
        world.policies = [p for p in world.policies if p.version == "v2"]

        with pytest.raises(KeyError):
            world.effective_policy("refund", as_of_day=10)


class TestSyntheticData:
    """All demo data is synthetic — a standing security requirement."""

    def test_emails_use_a_reserved_invalid_tld(self) -> None:
        for customer in build_world().customers.values():
            assert customer.email.endswith(".invalid")

    def test_world_contains_both_tiers(self) -> None:
        tiers = {c.tier for c in build_world().customers.values()}

        assert tiers == {CustomerTier.STANDARD, CustomerTier.PREMIUM}

    def test_no_order_predates_day_zero(self) -> None:
        world = build_world()

        assert all(order.placed_on_day >= 0 for order in world.orders.values())


class TestDescribeWorld:
    def test_summary_reports_state_hash(self) -> None:
        world = build_world()
        summary = describe_world(world)

        assert summary["state_hash"] == world.state_hash()
        assert summary["policy_versions"] == ["refund:v1", "refund:v2"]

    def test_summary_leaks_no_customer_data(self) -> None:
        summary = describe_world(build_world())

        assert "email" not in str(summary)


def test_world_rejects_unknown_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        World.model_validate({**build_world().model_dump(), "surprise": 1})
