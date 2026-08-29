"""Deterministic simulated world.

Everything the monitored agent can observe or change lives here. Two properties
matter more than realism:

* **Seeded determinism.** The same seed produces the same world, so replay can
  restore state and re-run from any point (D-001).
* **No wall clock.** Time is an integer ``day``. A world that consulted the real
  clock could not be replayed tomorrow and still behave the same.

Policies are *versioned* because policy staleness is one of the incident classes
we need to be able to inject (P3).
"""

from __future__ import annotations

import random
from copy import deepcopy
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.hashing import content_hash


class OrderStatus(StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class CustomerTier(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"


class Customer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    name: str
    tier: CustomerTier = CustomerTier.STANDARD
    # Synthetic throughout. No real person, no real address (D-002 / security rules).
    email: str


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    customer_id: str
    amount_cents: int = Field(ge=0)
    status: OrderStatus
    placed_on_day: int = Field(ge=0)
    item: str


class RefundPolicy(BaseModel):
    """A versioned policy. ``effective_from_day`` decides which version applies."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    version: str
    effective_from_day: int = Field(ge=0)
    refund_window_days: int = Field(ge=0)
    auto_refund_limit_cents: int = Field(ge=0)
    premium_window_bonus_days: int = Field(default=0, ge=0)


class RefundEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    amount_cents: int = Field(ge=0)
    policy_version: str
    approved_by: str | None = None


class World(BaseModel):
    """The complete simulated state. Snapshot-able and content-hashable."""

    model_config = ConfigDict(extra="forbid")

    day: int = Field(ge=0)
    seed: int
    customers: dict[str, Customer]
    orders: dict[str, Order]
    policies: list[RefundPolicy]
    refunds: list[RefundEntry] = Field(default_factory=list)
    cancellations: list[str] = Field(default_factory=list)
    approvals_requested: int = 0

    def snapshot(self) -> World:
        """A deep, independent copy — replay restores state from these."""
        return World.model_validate(deepcopy(self.model_dump()))

    def state_hash(self) -> str:
        """Content hash of the whole world; used to prove seeded determinism."""
        return content_hash(self.model_dump(mode="json"))

    def effective_policy(self, policy_id: str, as_of_day: int | None = None) -> RefundPolicy:
        """The policy version in force on a given day.

        Raises:
            KeyError: if no version of ``policy_id`` is effective yet.
        """
        day = self.day if as_of_day is None else as_of_day
        candidates = [
            policy
            for policy in self.policies
            if policy.policy_id == policy_id and policy.effective_from_day <= day
        ]
        if not candidates:
            raise KeyError(f"no effective version of policy {policy_id!r} on day {day}")
        return max(candidates, key=lambda p: (p.effective_from_day, p.version))

    def policy_version(self, policy_id: str, version: str) -> RefundPolicy:
        """A specific policy version.

        Raises:
            KeyError: if that version does not exist.
        """
        for policy in self.policies:
            if policy.policy_id == policy_id and policy.version == version:
                return policy
        raise KeyError(f"policy {policy_id!r} has no version {version!r}")

    def total_refunded(self, order_id: str) -> int:
        return sum(entry.amount_cents for entry in self.refunds if entry.order_id == order_id)


# Fixed synthetic corpus. Names and emails are obviously fake by construction.
_FIRST_NAMES = ("Ada", "Grace", "Alan", "Edsger", "Barbara", "Ken", "Radia", "Leslie")
_ITEMS = ("desk lamp", "keyboard", "monitor stand", "cable kit", "headphones")


def build_world(seed: int = 1337, *, day: int = 120, customer_count: int = 6) -> World:
    """Build a reproducible world.

    The same ``seed`` and arguments always produce a byte-identical world — the
    property `test_world_determinism` asserts.
    """
    rng = random.Random(seed)

    customers: dict[str, Customer] = {}
    for index in range(customer_count):
        customer_id = f"CUST-{1000 + index}"
        name = _FIRST_NAMES[index % len(_FIRST_NAMES)]
        customers[customer_id] = Customer(
            customer_id=customer_id,
            name=name,
            tier=CustomerTier.PREMIUM if index % 3 == 0 else CustomerTier.STANDARD,
            email=f"{name.lower()}.{index}@example.invalid",
        )

    customer_ids = sorted(customers)
    orders: dict[str, Order] = {}
    for index in range(customer_count * 2):
        order_id = f"ORD-{2000 + index}"
        orders[order_id] = Order(
            order_id=order_id,
            customer_id=customer_ids[index % len(customer_ids)],
            amount_cents=rng.randrange(1_500, 45_000, 100),
            status=rng.choice(list(OrderStatus)[:3]),
            placed_on_day=rng.randint(max(0, day - 100), day - 1),
            item=rng.choice(_ITEMS),
        )

    # Two versions: v2 supersedes v1 and tightens the refund window. The gap
    # between them is what a stale-policy injection exploits in P3.
    policies = [
        RefundPolicy(
            policy_id="refund",
            version="v1",
            effective_from_day=0,
            refund_window_days=90,
            auto_refund_limit_cents=30_000,
            premium_window_bonus_days=30,
        ),
        RefundPolicy(
            policy_id="refund",
            version="v2",
            effective_from_day=100,
            refund_window_days=30,
            auto_refund_limit_cents=20_000,
            premium_window_bonus_days=15,
        ),
    ]

    return World(
        day=day,
        seed=seed,
        customers=customers,
        orders=orders,
        policies=policies,
    )


def describe_world(world: World) -> dict[str, Any]:
    """Small summary for logging and debugging. Never includes secrets."""
    return {
        "day": world.day,
        "seed": world.seed,
        "customers": len(world.customers),
        "orders": len(world.orders),
        "policy_versions": [f"{p.policy_id}:{p.version}" for p in world.policies],
        "refunds": len(world.refunds),
        "state_hash": world.state_hash(),
    }
