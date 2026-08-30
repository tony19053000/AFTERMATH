"""Agent-count sweep: does adding investigators earn its cost?

D-008 committed to answering "how many agents?" with data rather than intuition.
P8.1 sharpened the question: because the pipeline now falls back to an
exhaustive sweep when no agent hypothesis survives measurement, **localization
is floored by the deterministic engine regardless of agent quality**. So
localization alone cannot isolate what investigators contribute.

The metric that can is **hypothesis recall** — does the union of N investigators
contain the true causal step? — reported against tokens and latency. An
investigator that never puts the right candidate on the table adds cost and
nothing else, and recall is where that shows up.

A null or negative result here is a finding, not a failure.

Deterministic apart from the provider handed in.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.hashing import content_hash
from aftermath.forensics.orchestrator import ForensicOrchestrator, HypothesisSource
from aftermath.injection.incidents import IncidentDefinition, load_incidents
from aftermath.injection.runner import run_incident


class ArmResult(BaseModel):
    """One configuration measured over the incident set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    investigators: int = Field(gt=0)
    incidents: int = Field(gt=0)
    # Union of agent hypotheses contained the true causal step.
    recall_hits: int = Field(ge=0)
    # Pipeline reached the true cause (floored by the sweep fallback).
    localized: int = Field(ge=0)
    # Times the agents produced nothing usable and the sweep had to rescue them.
    fallbacks: int = Field(ge=0)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0

    @property
    def recall(self) -> float:
        """The metric that isolates investigator contribution."""
        return self.recall_hits / self.incidents

    @property
    def localization_rate(self) -> float:
        return self.localized / self.incidents

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def tokens_per_incident(self) -> float:
        return self.total_tokens / self.incidents


class SweepReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arms: list[ArmResult]
    incident_ids: tuple[str, ...]

    def marginal_gain(self) -> list[dict[str, Any]]:
        """Recall and cost added by each step up in agent count.

        The point of the sweep: an arm that adds tokens without adding recall
        has not earned its place, however plausible more agents sounded.
        """
        rows: list[dict[str, Any]] = []
        for previous, current in zip(self.arms, self.arms[1:], strict=False):
            rows.append(
                {
                    "from_investigators": previous.investigators,
                    "to_investigators": current.investigators,
                    "recall_delta": current.recall - previous.recall,
                    "localization_delta": current.localization_rate
                    - previous.localization_rate,
                    "token_delta": current.total_tokens - previous.total_tokens,
                    "token_multiple": (
                        current.total_tokens / previous.total_tokens
                        if previous.total_tokens
                        else 0.0
                    ),
                }
            )
        return rows

    def to_artifact(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "incident_ids": list(self.incident_ids),
            "arms": [
                a.model_dump(mode="json")
                | {
                    "recall": a.recall,
                    "localization_rate": a.localization_rate,
                    "tokens_per_incident": a.tokens_per_incident,
                }
                for a in self.arms
            ],
            "marginal_gain": self.marginal_gain(),
        }
        payload["artifact_hash"] = content_hash(
            {
                **payload,
                "arms": [
                    {k: v for k, v in a.items() if k != "latency_seconds"}
                    for a in payload["arms"]
                ],
            }
        )
        return payload


class _TokenCounter:
    """Wraps a provider to account tokens per arm. Cost is half the measurement."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = f"counted({getattr(inner, 'name', '?')})"
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(self, request: Any) -> Any:
        response = self._inner.complete(request)
        self.prompt_tokens += response.usage.prompt_tokens
        self.completion_tokens += response.usage.completion_tokens
        return response


def run_sweep(
    provider: Any,
    counts: tuple[int, ...] = (1, 3, 5),
    *,
    incidents: dict[str, IncidentDefinition] | None = None,
    trials: int = 3,
    model: str | None = None,
) -> SweepReport:
    """Measure each investigator count over the identical incident set."""
    catalogue = incidents if incidents is not None else load_incidents()
    incident_ids = tuple(sorted(catalogue))
    truths = {
        i: run_incident(catalogue[i]).run.trace.injection.true_causal_step
        for i in incident_ids
    }

    arms: list[ArmResult] = []
    for count in counts:
        counter = _TokenCounter(provider)
        orchestrator = ForensicOrchestrator(
            counter, trials=trials, investigators=count, run_verifier=False
        )
        if model:
            orchestrator._model = model

        hits = localized = fallbacks = 0
        started = time.time()
        for incident_id in incident_ids:
            report = orchestrator.investigate(catalogue[incident_id])
            proposed = {h.suspected_step_id for h in report.hypotheses}
            # Recall is measured against what the AGENTS proposed. When the sweep
            # rescued the run, its candidates are not the agents' credit.
            if report.hypothesis_source is HypothesisSource.AGENT:
                hits += truths[incident_id] in proposed
            else:
                fallbacks += 1
            localized += report.root_cause_step == truths[incident_id]

        arms.append(
            ArmResult(
                investigators=count,
                incidents=len(incident_ids),
                recall_hits=hits,
                localized=localized,
                fallbacks=fallbacks,
                prompt_tokens=counter.prompt_tokens,
                completion_tokens=counter.completion_tokens,
                latency_seconds=time.time() - started,
            )
        )
    return SweepReport(arms=arms, incident_ids=incident_ids)
