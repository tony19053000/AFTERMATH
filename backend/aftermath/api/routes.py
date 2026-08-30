"""Read-only API over stored artifacts.

Every endpoint here serves something that exists on disk — an incident
definition, a recorded trace, a benchmark result, a regression case. Nothing is
computed for display, and nothing is invented when a file is missing: a missing
artifact is a 404, not an empty shape that renders as zeros.

That constraint exists because the UI is bound by `CLAUDE.md` §3: every number
shown anywhere must trace to a stored experiment artifact. The simplest way to
guarantee that is for the API to have nothing else to give.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from aftermath.config import REPO_ROOT
from aftermath.forensics.orchestrator import ForensicOrchestrator
from aftermath.immunity.runner import AgentVersion, run_suite
from aftermath.immunity.vault import ImmunityVault
from aftermath.injection.incidents import load_incidents
from aftermath.injection.runner import run_incident

RESULTS_DIR = REPO_ROOT / "data" / "results"
# Trials per counterfactual experiment when investigating on request. The agent
# is deterministic, so a small number establishes the same effect size as a
# large one and keeps the endpoint responsive.
EXPERIMENT_TRIALS = 3

router = APIRouter()


def _read_artifact(name: str) -> dict[str, Any]:
    """Load a stored result.

    Raises:
        HTTPException: 404 if the artifact has not been produced. The UI must
            show "not run" rather than a plausible-looking zero.
    """
    path = RESULTS_DIR / name
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{name} has not been produced yet — run the benchmark to create it",
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/incidents")
def list_incidents() -> dict[str, Any]:
    """The benchmark incident set, with ground truth resolved by running each."""
    incidents = load_incidents()
    rows = []
    for incident_id, definition in sorted(incidents.items()):
        trace = run_incident(definition).run.trace
        rows.append(
            {
                "incident_id": incident_id,
                "description": definition.description,
                "scenario_id": definition.scenario_id,
                "severity": definition.severity.value,
                "fault_kind": definition.injected_failure.kind.value,
                "fault_layer": definition.injected_failure.layer.value,
                "failing_oracle": definition.failing_oracle,
                "true_causal_step": trace.injection.true_causal_step,
                "observed_behavior": definition.observed_behavior,
                "expected_safe_behavior": definition.expected_safe_behavior,
                "step_count": len(trace.steps),
            }
        )
    return {"incidents": rows, "count": len(rows)}


@router.get("/incidents/{incident_id}/trace")
def get_trace(incident_id: str) -> dict[str, Any]:
    """The recorded trace for one incident, including its ground truth.

    Ground truth is included deliberately: this endpoint serves the *evidence
    board*, which is read by a human. The redaction that keeps it from agents
    lives in `forensics/redaction.py` and is a separate path.
    """
    incidents = load_incidents()
    if incident_id not in incidents:
        raise HTTPException(status_code=404, detail=f"unknown incident {incident_id}")

    trace = run_incident(incidents[incident_id]).run.trace
    return {
        "trace_id": trace.trace_id,
        "scenario_id": trace.scenario_id,
        "outcome": trace.outcome.model_dump(mode="json"),
        "injection": trace.injection.model_dump(mode="json") if trace.injection else None,
        "content_hash": trace.content_hash(),
        "steps": [s.model_dump(mode="json") for s in trace.steps],
    }


@router.get("/incidents/{incident_id}/investigation")
def investigate(incident_id: str) -> dict[str, Any]:
    """Run the forensic pipeline for one incident and return what it established.

    Executed on request, deterministically and with no model: the hypotheses are
    the exhaustive candidate set, the effect sizes are measured by replay, and
    the repair numbers come from actually applying the guard. Nothing here is
    read from a canned report, so a viewer sees what the engine concludes about
    *this* incident today.

    Raises:
        HTTPException: 404 for an unknown incident.
    """
    incidents = load_incidents()
    if incident_id not in incidents:
        raise HTTPException(status_code=404, detail=f"unknown incident {incident_id}")

    definition = incidents[incident_id]
    trace = run_incident(definition).run.trace
    report = ForensicOrchestrator(None, trials=EXPERIMENT_TRIALS).investigate(definition)

    vault_case = next(
        (c for c in ImmunityVault().load_all() if c.incident_id == incident_id), None
    )

    return {
        "incident_id": incident_id,
        "description": definition.description,
        "expected_behavior": definition.expected_behavior,
        "observed_behavior": definition.observed_behavior,
        "expected_safe_behavior": definition.expected_safe_behavior,
        "severity": definition.severity.value,
        "scenario_id": definition.scenario_id,
        "step_count": len(trace.steps),
        "outcome": trace.outcome.model_dump(mode="json"),
        "true_causal_step": trace.injection.true_causal_step,
        "hypothesis_source": report.hypothesis_source.value,
        "experiments": [
            {
                "step_id": e["intervention"]["step_id"],
                "kind": e["intervention"]["kind"],
                "baseline_failures": e["baseline"]["failures"],
                "intervened_failures": e["intervened"]["failures"],
                "trials": e["baseline"]["trials"],
                "effect_size": e["effect_size"],
                "prevented": e["prevented"],
                "artifact_hash": e["artifact_hash"],
            }
            for e in report.experiments
        ],
        "root_cause_step": report.root_cause_step,
        "resolution": report.resolution.value,
        "resolved_by_measurement": report.resolved_by_measurement,
        "repair": report.repair,
        "repair_accepted": report.repair_accepted,
        # Immunity is claimed only when a case genuinely exists in the vault.
        "immunity": {
            "acquired": vault_case is not None,
            "case_id": vault_case.case_id if vault_case else None,
            "verified_repair": vault_case.verified_repair.kind.value if vault_case else None,
        },
        "agent_errors": report.agent_errors,
    }


@router.get("/benchmark")
def get_benchmark() -> dict[str, Any]:
    """The published benchmark comparison."""
    return _read_artifact("benchmark.json")


@router.get("/benchmark/history")
def get_benchmark_history() -> dict[str, Any]:
    """Current and superseded results, so a change is visible rather than replaced."""
    runs = []
    for name, label in (
        ("benchmark_p7_pre_fallback.json", "P7 — before sweep fallback"),
        ("benchmark.json", "P8.1 — with sweep fallback"),
    ):
        path = RESULTS_DIR / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs.append(
            {
                "label": label,
                "artifact": name,
                "aftermath": payload["aftermath_localization_rate"],
                "baseline": payload["baseline_localization_rate"],
                "verdict": payload["verdict"],
            }
        )
    return {"runs": runs}


@router.get("/sweep")
def get_sweep() -> dict[str, Any]:
    """The agent-count study."""
    return _read_artifact("investigator_recall_sweep.json")


@router.get("/immunity")
def get_immunity() -> dict[str, Any]:
    """The vault, and the release gate run against both agent versions.

    The gate is executed on request rather than read from a file: it is a
    property of the *current* code, and a stale stored verdict would be exactly
    the kind of decorative number this project forbids.
    """
    vault = ImmunityVault()
    cases = vault.load_all()
    repairs = vault.repairs_of_record()

    unrepaired = run_suite(cases, AgentVersion.unrepaired())
    repaired = run_suite(cases, AgentVersion("all-guardrails", repairs))

    return {
        "cases": [
            {
                "case_id": c.case_id,
                "incident_id": c.incident_id,
                "scenario_id": c.scenario_id,
                "root_cause_step": c.root_cause_step,
                "repair": c.verified_repair.kind.value,
                "effect_size": c.evidence_effect_size,
                "severity": c.severity.value,
            }
            for c in cases
        ],
        "guardrails": [r.kind.value for r in repairs],
        "gate": {
            "unrepaired": {
                "protected": len(unrepaired.protected),
                "regressions": len(unrepaired.regressions),
                "verdict": unrepaired.verdict,
            },
            "repaired": {
                "protected": len(repaired.protected),
                "regressions": len(repaired.regressions),
                "verdict": repaired.verdict,
                "regressed_cases": [r.case_id for r in repaired.regressions],
            },
        },
    }


@router.get("/immunity/drop/{guardrail}")
def drop_guardrail(guardrail: str) -> dict[str, Any]:
    """Replay the suite with one guardrail removed — the release-gate demo.

    This is a real execution, not a stored scenario: the caller picks a
    guardrail and the suite runs without it.
    """
    vault = ImmunityVault()
    repairs = vault.repairs_of_record()
    if guardrail not in {r.kind.value for r in repairs}:
        raise HTTPException(status_code=404, detail=f"unknown guardrail {guardrail}")

    remaining = tuple(r for r in repairs if r.kind.value != guardrail)
    report = run_suite(vault.load_all(), AgentVersion(f"without-{guardrail}", remaining))
    return {
        "dropped": guardrail,
        "protected": len(report.protected),
        "regressions": [
            {"case_id": r.case_id, "incident_id": r.incident_id, "detail": r.detail}
            for r in report.regressions
        ],
        "verdict": report.verdict,
    }
