"""Fault injection specifications.

An injection is a *controlled* perturbation. Because we choose it, we know the
true cause — which is the entire reason the benchmark is synthetic (D-002).

Four layers, matching the places real agent systems actually break:

* ``TOOL_RESULT``  — a tool returns something wrong (stale, malformed, mislabeled)
* ``WORLD_STATE``  — the environment is not what the agent assumes
* ``CONTEXT``      — information is dropped or altered before the agent sees it
* ``RETRY``        — an operation is duplicated, as a retry storm would

Ground truth is recorded by the injector at injection time and never inferred,
never asked of a model.

**CONTEXT is taxonomy only for now — no kind implements it.** The MVP agent has a
narrow data flow: `calculate_refund` re-reads the customer from world state by
`order.customer_id` rather than using the record `get_customer` returned, so
altering that call's arguments changes nothing the agent decides. A fault that
cannot affect an outcome is not an incident, and shipping one would have put a
guaranteed-passing case into the benchmark. A spec declaring this layer simply
never fires, and `run_incident` raises rather than reporting a false negative.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.trace import Severity


class InjectionLayer(StrEnum):
    TOOL_RESULT = "tool_result"
    WORLD_STATE = "world_state"
    CONTEXT = "context"
    RETRY = "retry"


class InjectionKind(StrEnum):
    """The concrete fault mechanisms implemented so far."""

    STALE_POLICY = "stale_policy"
    DUPLICATE_REFUND_RETRY = "duplicate_refund_retry"
    APPROVAL_BYPASS = "approval_bypass"
    MALFORMED_POLICY_OUTPUT = "malformed_policy_output"
    # Generic: set one field of a tool result to a chosen value. One mechanism
    # covers many distinct incidents (inflated amounts, forced eligibility,
    # raised limits, wrong order data) without a bespoke kind for each, which
    # keeps the injector small and the incidents comparable to one another.
    OVERRIDE_RESULT_FIELD = "override_result_field"


class InjectionSpec(BaseModel):
    """What to perturb, where, and how.

    ``target_tool`` plus ``occurrence`` identify the exact call to hit, so an
    incident is reproducible rather than "whichever call happened to match".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: InjectionKind
    layer: InjectionLayer
    target_tool: str | None = None
    # 1-based: which matching call to perturb. Hitting "every" call would make
    # the causal step ambiguous, which defeats the purpose.
    occurrence: int = Field(default=1, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.HIGH

    def describes_tool(self, tool: str) -> bool:
        return self.target_tool is None or self.target_tool == tool
