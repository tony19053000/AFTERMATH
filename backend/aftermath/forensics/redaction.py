"""What a forensic agent is allowed to see.

An agent must never receive the incident's ground truth. If it could see
`true_causal_step`, every accuracy number the project reports would be
meaningless (D-002). This is the single place that boundary is enforced, and
`test_agents_never_see_ground_truth` asserts it.
"""

from __future__ import annotations

from typing import Any

from aftermath.core.trace import Trace

# Keys that would leak the answer or the verdict the agent is meant to reason toward.
FORBIDDEN_KEYS = frozenset({"injection", "true_causal_step", "injected_failure"})


def redact_for_agent(trace: Trace) -> dict[str, Any]:
    """The trace as an agent sees it: steps and context, no ground truth.

    The run's outcome is included — an investigator legitimately knows the run
    failed and what the oracle said, exactly as a human engineer would. What it
    must not know is *which step* was perturbed.
    """
    payload = {
        "trace_id": trace.trace_id,
        "scenario_id": trace.scenario_id,
        "agent_version": trace.agent_version,
        "outcome": trace.outcome.model_dump(mode="json"),
        "steps": [
            {k: v for k, v in step.model_dump(mode="json").items() if k not in ("ts",)}
            for step in trace.steps
        ],
    }
    assert not (FORBIDDEN_KEYS & payload.keys())
    return payload


def contains_ground_truth(payload: Any) -> bool:
    """True if a serialized payload leaks anything that identifies the injected fault."""
    text = str(payload)
    return any(key in text for key in FORBIDDEN_KEYS)
