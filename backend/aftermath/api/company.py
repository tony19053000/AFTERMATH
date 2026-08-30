"""The monitored company's operations view — the first half of the product story.

This serves the *same* simulated agent, world, and incidents the forensic side
analyses. It adds no simulation of its own: a demo run here calls
`run_clean` / `run_incident` exactly as the benchmark does, and returns the real
trace those produce.

That is the point. The company screen and the forensic screen must be looking at
one execution, not at two that resemble each other — otherwise "investigate this
incident" would open something merely similar to what the user just watched.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from aftermath.companyagent.scenarios import get_scenario
from aftermath.companyagent.world import build_world
from aftermath.core.trace import OutcomeStatus, StepType, Trace
from aftermath.injection.incidents import load_incidents
from aftermath.injection.runner import run_clean, run_incident

router = APIRouter()

COMPANY = "NovaCommerce"

# The demo incident. Chosen because it is the clearest to watch fail: the order
# is worth 17,200 and the agent refunds 99,000. It also localizes uniquely, has
# an accepted repair, and already holds a case in the Immunity Vault — so the
# whole story runs on real artifacts rather than a fixture built for the demo.
DEMO_INCIDENT = "I-007"

# Human wording for the tool calls, so the operations view reads like an
# activity feed rather than a stack trace. Purely presentational: the steps
# themselves come from the trace.
TOOL_LABELS = {
    "get_customer": "Looking up customer record",
    "get_order": "Fetching order details",
    "get_policy": "Reading refund policy",
    "calculate_refund": "Calculating refund amount",
    "request_human_approval": "Requesting supervisor approval",
    "issue_simulated_refund": "Issuing refund",
    "cancel_order": "Cancelling order",
}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # When set, the run is executed with that incident's fault applied. When
    # null, the same scenario runs healthy — so a viewer can see the normal
    # path before the failure, and compare.
    incident_id: str | None = Field(default=DEMO_INCIDENT)


def _money(cents: int | None) -> str | None:
    return None if cents is None else f"{cents / 100:,.2f}"


def _activity(trace: Trace) -> list[dict[str, Any]]:
    """The agent's actions, as an operations feed.

    Built strictly from trace steps. A step the agent did not take cannot appear
    here, and every entry keeps its `step_id` so the forensic view can be
    cross-referenced against what the operator watched.
    """
    feed: list[dict[str, Any]] = []
    results = {
        s.call_id: s for s in trace.steps if s.type is StepType.TOOL_RESULT
    }
    for step in trace.steps:
        if step.type is StepType.TOOL_CALL:
            result = results.get(step.call_id)
            feed.append(
                {
                    "step_id": step.step_id,
                    "kind": "tool",
                    "label": TOOL_LABELS.get(step.tool, step.tool),
                    "tool": step.tool,
                    "arguments": step.arguments,
                    "result": result.result if result else None,
                    "error": result.error if result else None,
                    "result_step_id": result.step_id if result else None,
                }
            )
        elif step.type is StepType.APPROVAL_REQUEST:
            feed.append(
                {
                    "step_id": step.step_id,
                    "kind": "approval",
                    "label": "Supervisor approval " + ("granted" if step.granted else "denied"),
                    "granted": step.granted,
                }
            )
        elif step.type is StepType.FINAL_OUTPUT:
            feed.append(
                {"step_id": step.step_id, "kind": "reply", "label": "Reply to customer",
                 "text": step.text}
            )
    return feed


def _context(scenario_id: str, order_id: str) -> dict[str, Any]:
    """Customer and order panel, read from the simulated world — not restated."""
    world = build_world()
    order = world.orders[order_id]
    customer = world.customers[order.customer_id]
    policy = world.effective_policy("refund")

    window = policy.refund_window_days
    if customer.tier == "premium":
        window += policy.premium_window_bonus_days
    age = world.day - order.placed_on_day

    return {
        "customer": {
            "id": customer.customer_id,
            "name": customer.name,
            "tier": customer.tier.value,
            "email": customer.email,
        },
        "order": {
            "id": order.order_id,
            "item": order.item,
            "amount": _money(order.amount_cents),
            "amount_cents": order.amount_cents,
            "status": order.status.value,
            "age_days": age,
        },
        "policy": {
            "version": policy.version,
            "window_days": window,
            "auto_approve_limit": _money(policy.auto_refund_limit_cents),
            "auto_approve_limit_cents": policy.auto_refund_limit_cents,
        },
        "eligibility": {
            "within_window": age <= window,
            "entitled": _money(order.amount_cents if age <= window else 0),
            "entitled_cents": order.amount_cents if age <= window else 0,
            "needs_approval": order.amount_cents > policy.auto_refund_limit_cents,
        },
    }


@router.get("/company/scenarios")
def scenarios() -> dict[str, Any]:
    """What the demo can run. The incident is a real benchmark incident."""
    incident = load_incidents()[DEMO_INCIDENT]
    scenario = get_scenario(incident.scenario_id)
    return {
        "company": COMPANY,
        "demo_incident": DEMO_INCIDENT,
        "scenario_id": incident.scenario_id,
        "customer_message": scenario.user_text,
        "description": incident.description,
        "expected_behavior": incident.expected_behavior,
        "severity": incident.severity.value,
    }


@router.post("/company/run")
def run(request: RunRequest) -> dict[str, Any]:
    """Execute the monitored agent for real and report what happened.

    Raises:
        HTTPException: 404 for an unknown incident. There is no "demo mode"
            fallback — if the run cannot be executed, nothing is displayed.
    """
    incidents = load_incidents()
    incident_id = request.incident_id

    if incident_id is not None and incident_id not in incidents:
        raise HTTPException(status_code=404, detail=f"unknown incident {incident_id}")

    if incident_id is None:
        scenario_id = incidents[DEMO_INCIDENT].scenario_id
        trace = run_clean(scenario_id).trace
        definition = None
    else:
        definition = incidents[incident_id]
        scenario_id = definition.scenario_id
        trace = run_incident(definition).run.trace

    scenario = get_scenario(scenario_id)
    failed = trace.outcome.status is OutcomeStatus.FAIL

    refunded = None
    for step in trace.steps:
        if step.type is StepType.TOOL_RESULT and step.tool == "issue_simulated_refund":
            if step.result:
                refunded = step.result.get("amount_cents")

    context = _context(scenario_id, scenario.order_id)

    payload: dict[str, Any] = {
        "company": COMPANY,
        "incident_id": incident_id,
        "scenario_id": scenario_id,
        "trace_id": trace.trace_id,
        "customer_message": scenario.user_text,
        "context": context,
        "activity": _activity(trace),
        "step_count": len(trace.steps),
        "outcome": {
            "status": trace.outcome.status.value,
            "oracle": trace.outcome.oracle,
            "detail": trace.outcome.detail,
        },
        "refunded": _money(refunded),
        "refunded_cents": refunded,
        "monitoring": {"product": "AFTERMATH", "connected": True, "captured": failed},
    }

    if failed and definition is not None:
        payload["incident"] = {
            "incident_id": incident_id,
            "severity": definition.severity.value,
            "expected": context["eligibility"]["entitled"],
            "expected_cents": context["eligibility"]["entitled_cents"],
            "observed": _money(refunded),
            "observed_cents": refunded,
            "observed_behavior": definition.observed_behavior,
            "expected_behavior": definition.expected_behavior,
            "captured_steps": len(trace.steps),
        }
    return payload
