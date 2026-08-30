"""Running both systems over the identical incident set.

Fairness is enforced structurally, not by convention: one incident list is built
once and both systems iterate the same list. `Comparison.incident_ids` records
it, and a test asserts both systems were scored over the same set.

Deterministic apart from the provider handed to the baseline and to AFTERMATH's
agents — and both receive the same one.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from aftermath.benchmark.baseline import diagnose
from aftermath.benchmark.grader import GradedAnswer, grade
from aftermath.benchmark.metrics import Comparison, summarize
from aftermath.config import DEFAULT_MODEL
from aftermath.forensics.orchestrator import ForensicOrchestrator
from aftermath.injection.incidents import IncidentDefinition, load_incidents
from aftermath.injection.runner import run_incident

AFTERMATH = "aftermath"
BASELINE = "baseline"


def run_benchmark(
    provider: Any = None,
    *,
    incidents: dict[str, IncidentDefinition] | None = None,
    trials: int = 3,
    model: str = DEFAULT_MODEL,
    artifact_path: Path | None = None,
) -> Comparison:
    """Run both systems over one incident set and compute the comparison.

    ``provider`` is shared: AFTERMATH's agents and the baseline get the same
    model, which is what makes the comparison a test of the engineering system
    rather than of model capability (D-007). With ``provider=None`` AFTERMATH
    runs its deterministic path and the baseline cannot answer at all — useful
    for wiring tests, not for a published result.
    """
    catalogue = incidents if incidents is not None else load_incidents()
    incident_ids = tuple(sorted(catalogue))

    orchestrator = ForensicOrchestrator(provider, trials=trials)
    if provider is not None:
        orchestrator._model = model

    am_answers: list[GradedAnswer] = []
    base_answers: list[GradedAnswer] = []
    base_prompt = base_completion = 0

    started = time.time()
    for incident_id in incident_ids:
        incident = catalogue[incident_id]
        report = orchestrator.investigate(incident)
        am_answers.append(grade(incident, AFTERMATH, report.root_cause_step))
    am_seconds = time.time() - started

    started = time.time()
    for incident_id in incident_ids:
        incident = catalogue[incident_id]
        if provider is None:
            base_answers.append(grade(incident, BASELINE, None))
            continue
        trace = run_incident(incident).run.trace
        result = diagnose(provider, incident_id, trace, model=model)
        base_prompt += result.prompt_tokens
        base_completion += result.completion_tokens
        answered = result.diagnosis.root_cause_step_id if result.answered else None
        base_answers.append(grade(incident, BASELINE, answered))
    base_seconds = time.time() - started

    comparison = Comparison(
        aftermath=summarize(AFTERMATH, am_answers, latency_seconds=am_seconds),
        baseline=summarize(
            BASELINE,
            base_answers,
            prompt_tokens=base_prompt,
            completion_tokens=base_completion,
            latency_seconds=base_seconds,
        ),
        incident_ids=incident_ids,
    )

    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        payload = comparison.to_artifact()
        payload["per_incident"] = [
            {
                "incident_id": a.incident_id,
                "aftermath": a.verdict.value,
                "aftermath_answer": a.answered_step,
                "baseline": b.verdict.value,
                "baseline_answer": b.answered_step,
                "true_causal_step": a.true_causal_step,
                "causal_set": list(a.causal_set),
            }
            for a, b in zip(am_answers, base_answers, strict=True)
        ]
        artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return comparison
