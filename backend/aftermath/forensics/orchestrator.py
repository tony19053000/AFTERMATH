"""The forensic pipeline.

    redacted trace -> investigate -> plan -> EXPERIMENT -> rank -> refine
                                                  |
                                          repair -> EVALUATE -> verify -> report

Capitalised stages are deterministic Python. Everything the agents produce is a
proposal that gets measured; nothing they say is treated as a result.

Three properties this file is responsible for:

* agents never receive ground truth (redaction),
* the reported cause is chosen by measured effect, never by agent confidence,
* every causal claim in the report cites an experiment artifact.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.core.hashing import content_hash
from aftermath.core.trace import StepType, Trace
from aftermath.forensics.agents import (
    CounterfactualPlanner,
    Investigator,
    RepairAgent,
    Verifier,
    lenses_for,
)
from aftermath.forensics.parsing import AgentOutputError
from aftermath.llm.base import LLMError
from aftermath.forensics.redaction import redact_for_agent
from aftermath.forensics.schemas import Hypothesis, PlannedExperiment
from aftermath.injection.incidents import IncidentDefinition
from aftermath.injection.runner import NORMAL_CASES, run_clean, run_incident
from aftermath.replay.chain import refine_to_root_cause
from aftermath.replay.engine import ReplayEngine
from aftermath.replay.experiment import ExperimentResult, ExperimentRunner, rank_by_effect
from aftermath.replay.intervention import (
    InterventionKind,
    InterventionSpec,
    TargetNotFoundError,
    addressable_steps,
)
from aftermath.replay.repair import RepairEvaluation, RepairSpec, evaluate_repair

EFFECT_THRESHOLD = 0.5


class HypothesisSource(StrEnum):
    AGENT = "agent"
    # Used when the investigator produced nothing usable. Honest and effective,
    # but it means the model contributed nothing to that run, so the report says so.
    EXHAUSTIVE_FALLBACK = "exhaustive_fallback"
    # The agent proposed hypotheses, none survived measurement, and the
    # exhaustive sweep was run as a second pass. Recorded distinctly so a report
    # never implies the agent found something it did not.
    AGENT_THEN_SWEEP = "agent_then_sweep"


class CauseResolution(StrEnum):
    UNIQUE = "unique_effect"
    DOMINANCE_MEASURED = "dominance_measured"
    EARLIEST_STEP_HEURISTIC = "earliest_step_heuristic"
    NONE = "no_cause_found"


class ForensicReport(BaseModel):
    """The pipeline's output. Every causal claim carries its evidence."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    hypothesis_source: HypothesisSource
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    experiments: list[dict[str, Any]] = Field(default_factory=list)
    tied_steps: list[str] = Field(default_factory=list)
    root_cause_step: str | None = None
    resolution: CauseResolution = CauseResolution.NONE
    dominance_evidence: list[dict[str, Any]] = Field(default_factory=list)
    repair: dict[str, Any] | None = None
    repair_accepted: bool = False
    repair_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    agent_errors: list[str] = Field(default_factory=list)

    @property
    def resolved_by_measurement(self) -> bool:
        """False when the answer leaned on the tie-break rather than evidence."""
        return self.resolution in (
            CauseResolution.UNIQUE,
            CauseResolution.DOMINANCE_MEASURED,
        )

    def artifact_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class ForensicOrchestrator:
    """Runs the pipeline for one incident."""

    def __init__(
        self,
        provider: Any = None,
        *,
        trials: int = 5,
        engine: ReplayEngine | None = None,
        investigators: int = 1,
        run_verifier: bool = True,
    ) -> None:
        self._provider = provider
        self._trials = trials
        # Number of investigator agents, each with a distinct lens. D-008: this
        # is configuration, never hard-coded, so agent count can be swept.
        self._investigators = investigators
        # The verifier does not affect localization. It can be switched off for
        # a sweep so the measurement is not paying for a stage it is not testing.
        self._run_verifier = run_verifier
        self._engine = engine or ReplayEngine()
        self._runner = ExperimentRunner(self._engine)

    # ---- stages --------------------------------------------------------------

    def _hypothesize(
        self, trace: Trace, errors: list[str]
    ) -> tuple[list[Hypothesis], HypothesisSource]:
        if self._provider is not None:
            redacted = redact_for_agent(trace)
            real_steps = {s.step_id for s in trace.steps}
            # Union across investigators, deduped by step. Distinct lenses are
            # expected to overlap; the union is what the evidence engine tests.
            merged: dict[str, Hypothesis] = {}
            for lens in lenses_for(self._investigators):
                try:
                    output = Investigator(self._provider, lens=lens).investigate(redacted)
                except (AgentOutputError, LLMError) as exc:
                    errors.append(f"investigator[{lens or 'general'}]: {exc}")
                    continue
                for hypothesis in output.hypotheses:
                    if hypothesis.suspected_step_id not in real_steps:
                        continue
                    existing = merged.get(hypothesis.suspected_step_id)
                    if existing is None or hypothesis.confidence > existing.confidence:
                        merged[hypothesis.suspected_step_id] = hypothesis
            if merged:
                return list(merged.values()), HypothesisSource.AGENT
            errors.append("investigator: no hypothesis named a real step")

        return self._exhaustive_candidates(trace), HypothesisSource.EXHAUSTIVE_FALLBACK

    @staticmethod
    def _exhaustive_candidates(trace: Trace) -> list[Hypothesis]:
        """Every step worth testing: value-carrying results AND duplicated actions.

        A retry fault lives on a `tool_call`, so a sweep over results alone would
        be structurally unable to find it.
        """
        candidates = list(addressable_steps(trace)) + [
            s.step_id
            for s in trace.steps
            if s.type is StepType.TOOL_CALL and _is_duplicate_call(trace, s.step_id)
        ]
        return [
            Hypothesis(
                suspected_step_id=step_id,
                mechanism="exhaustive candidate",
                confidence=0.0,
            )
            for step_id in sorted(set(candidates))
        ]

    def _plan(
        self, trace: Trace, hypotheses: list[Hypothesis], errors: list[str]
    ) -> list[PlannedExperiment]:
        step_types = {
            s.step_id: ("duplicate_call" if _is_duplicate_call(trace, s.step_id) else s.type.value)
            for s in trace.steps
            if s.type in (StepType.TOOL_CALL, StepType.TOOL_RESULT)
        }
        if self._provider is not None:
            try:
                output = CounterfactualPlanner(self._provider).plan(
                    [h.model_dump(mode="json") for h in hypotheses], step_types
                )
                if output.experiments:
                    return output.experiments
                errors.append("planner: produced no experiments")
            except (AgentOutputError, LLMError) as exc:
                errors.append(f"planner: {exc}")

        # Deterministic default: skip duplicated actions, replace wrong values.
        return [
            PlannedExperiment(
                suspected_step_id=h.suspected_step_id,
                intervention_kind=(
                    InterventionKind.SKIP_TOOL_CALL
                    if _is_duplicate_call(trace, h.suspected_step_id)
                    else InterventionKind.REPLACE_TOOL_RESULT
                ),
                rationale="default plan",
            )
            for h in hypotheses
        ]

    def _experiment(
        self,
        incident: IncidentDefinition,
        trace: Trace,
        healthy: Trace,
        planned: list[PlannedExperiment],
        hypotheses: list[Hypothesis],
        errors: list[str],
    ) -> tuple[list[ExperimentResult], dict[str, InterventionSpec]]:
        natural = {
            s.tool: s.result
            for s in healthy.steps
            if s.type is StepType.TOOL_RESULT and s.result is not None
        }
        confidence = {h.suspected_step_id: h.confidence for h in hypotheses}

        results: list[ExperimentResult] = []
        specs: dict[str, InterventionSpec] = {}
        for plan in planned:
            spec, reason = _build_spec(trace, plan, natural)
            if spec is None:
                errors.append(f"experiment skipped at {plan.suspected_step_id}: {reason}")
                continue
            try:
                results.append(
                    self._runner.run(
                        scenario_id=incident.scenario_id,
                        seed=incident.replay_configuration.seed,
                        injection=incident.injected_failure,
                        intervention=spec,
                        trials=self._trials,
                        incident_id=incident.incident_id,
                        proposer_confidence=confidence.get(plan.suspected_step_id),
                    )
                )
                specs[plan.suspected_step_id] = spec
            except TargetNotFoundError as exc:
                errors.append(f"experiment: {exc}")
        return results, specs

    # ---- entry point ---------------------------------------------------------

    def investigate(self, incident: IncidentDefinition) -> ForensicReport:
        """Run the full pipeline for one incident."""
        errors: list[str] = []
        trace = run_incident(incident).run.trace
        healthy = run_clean(incident.scenario_id).trace

        hypotheses, source = self._hypothesize(trace, errors)
        planned = self._plan(trace, hypotheses, errors)
        results, specs = self._experiment(incident, trace, healthy, planned, hypotheses, errors)

        ranked = rank_by_effect(results)
        tied = [r.intervention.step_id for r in ranked if r.effect_size >= EFFECT_THRESHOLD]

        # P8.1: agent hypotheses that survive no measurement leave the pipeline
        # with nothing to test, and it abstains. Measured in P7 as the single
        # largest source of lost accuracy (4 of 5 misses). The evidence engine
        # can enumerate candidates itself, so fall back to the exhaustive sweep
        # rather than reporting no cause. Recorded as AGENT_THEN_SWEEP so the
        # report never credits the agent with a cause the sweep found.
        if not tied and source is HypothesisSource.AGENT:
            errors.append("no agent hypothesis survived measurement; ran exhaustive sweep")
            hypotheses = self._exhaustive_candidates(trace)
            planned = self._plan(trace, hypotheses, errors)
            results, specs = self._experiment(
                incident, trace, healthy, planned, hypotheses, errors
            )
            ranked = rank_by_effect(results)
            tied = [r.intervention.step_id for r in ranked if r.effect_size >= EFFECT_THRESHOLD]
            source = HypothesisSource.AGENT_THEN_SWEEP

        root, resolution, edges = self._resolve_cause(incident, trace, healthy, tied, specs)

        repair, alternatives = self._repair(incident, trace, root, errors)
        verification = self._verify(ranked, repair, resolution, errors)

        return ForensicReport(
            incident_id=incident.incident_id,
            hypothesis_source=source,
            hypotheses=hypotheses,
            experiments=[r.to_artifact() for r in ranked],
            tied_steps=tied,
            root_cause_step=root,
            resolution=resolution,
            dominance_evidence=[vars(e) for e in edges],
            repair=_repair_artifact(repair),
            repair_accepted=bool(repair and repair.acceptable),
            repair_alternatives=alternatives,
            verification=verification,
            agent_errors=errors,
        )

    def _resolve_cause(self, incident, trace, healthy, tied, specs):
        if not tied:
            return None, CauseResolution.NONE, []
        if len(tied) == 1:
            return tied[0], CauseResolution.UNIQUE, []

        root, edges = refine_to_root_cause(
            self._engine,
            scenario_id=incident.scenario_id,
            seed=incident.replay_configuration.seed,
            injection=incident.injected_failure,
            baseline_trace=trace,
            healthy_trace=healthy,
            tied=[(s, specs[s]) for s in tied if s in specs],
        )
        if root is not None:
            return root, CauseResolution.DOMINANCE_MEASURED, edges
        # Ambiguous chain. Fall back to the earliest step, and SAY it is a
        # heuristic rather than presenting it as evidence (D-016).
        return min(tied), CauseResolution.EARLIEST_STEP_HEURISTIC, edges

    def _repair(
        self, incident: IncidentDefinition, trace: Trace, root: str | None, errors: list[str]
    ) -> tuple[RepairEvaluation | None, list[dict[str, Any]]]:
        if root is None:
            return None, []

        candidates: list[RepairSpec] = []
        if self._provider is not None:
            try:
                evidence = {
                    "root_cause_step": root,
                    "step": trace.step(root).model_dump(mode="json"),
                    "outcome": trace.outcome.model_dump(mode="json"),
                }
                candidates = [
                    RepairSpec(kind=p.kind, rationale=p.rationale)
                    for p in RepairAgent(self._provider).propose(evidence).proposals
                ]
            except (AgentOutputError, LLMError) as exc:
                errors.append(f"repair agent: {exc}")

        if not candidates:
            from aftermath.replay.repair import RepairKind

            candidates = [RepairSpec(kind=k) for k in RepairKind]

        evaluations = [
            evaluate_repair(
                spec,
                scenario_id=incident.scenario_id,
                seed=incident.replay_configuration.seed,
                injection=incident.injected_failure,
                normal_case_ids=NORMAL_CASES,
                trials=self._trials,
                engine=self._engine,
            )
            for spec in candidates
        ]
        # Selection is by measurement, and acceptability comes first: a guard
        # that prevents the incident by breaking legitimate cases must never win
        # over one that does neither harm. When nothing is acceptable, the best
        # available is still reported — flagged, not disguised as a solution.
        evaluations.sort(
            key=lambda e: (not e.acceptable, -e.prevention_rate, e.false_block_rate)
        )
        best = evaluations[0]
        alternatives = [_repair_artifact(e) for e in evaluations[1:]]
        return best, alternatives

    def _verify(self, ranked, repair, resolution, errors) -> dict[str, Any] | None:
        if self._provider is None or not self._run_verifier:
            return None
        try:
            return (
                Verifier(self._provider)
                .verify(
                    {
                        "experiments": [r.to_artifact() for r in ranked[:5]],
                        "resolution": resolution.value,
                        "repair": repair.model_dump(mode="json") if repair else None,
                        "prevention_rate": repair.prevention_rate if repair else None,
                        "false_block_rate": repair.false_block_rate if repair else None,
                    }
                )
                .model_dump(mode="json")
            )
        except (AgentOutputError, LLMError) as exc:
            errors.append(f"verifier: {exc}")
            return None


def _repair_artifact(evaluation: RepairEvaluation | None) -> dict[str, Any] | None:
    """Flatten a repair evaluation so every reported number sits at the top level."""
    if evaluation is None:
        return None
    return {
        "kind": evaluation.repair.kind.value,
        "rationale": evaluation.repair.rationale,
        "prevention_rate": evaluation.prevention_rate,
        "false_block_rate": evaluation.false_block_rate,
        "acceptable": evaluation.acceptable,
        "incident_trials": evaluation.incident_trials,
        "normal_cases": evaluation.normal_cases,
        "normal_cases_broken": evaluation.normal_cases_broken,
    }


def _is_duplicate_call(trace: Trace, step_id: str) -> bool:
    """Is this step a repeat of an earlier call to the same tool with the same args?"""
    target = next((s for s in trace.steps if s.step_id == step_id), None)
    if target is None or target.type is not StepType.TOOL_CALL:
        return False
    for step in trace.steps:
        if step.step_id == step_id:
            break
        if (
            step.type is StepType.TOOL_CALL
            and step.tool == target.tool
            and step.arguments == target.arguments
        ):
            return True
    return False


def _build_spec(
    trace: Trace, plan: PlannedExperiment, natural: dict[str, Any]
) -> tuple[InterventionSpec | None, str]:
    """Turn a planned experiment into an executable spec, or explain why not."""
    step = next((s for s in trace.steps if s.step_id == plan.suspected_step_id), None)
    if step is None:
        return None, "step does not exist in this trace"

    if plan.intervention_kind is InterventionKind.SKIP_TOOL_CALL:
        if step.type is not StepType.TOOL_CALL:
            return None, "skip_tool_call needs a tool_call step, not a result"
        return (
            InterventionSpec(
                kind=InterventionKind.SKIP_TOOL_CALL,
                step_id=plan.suspected_step_id,
                rationale=plan.rationale,
            ),
            "",
        )

    replacement = natural.get(getattr(step, "tool", None))
    if replacement is None:
        # The healthy run never made this call, so there is no "correct value"
        # to substitute. The step may still be causal via a different
        # intervention kind — this is a limit of the experiment, not a verdict.
        return None, (
            f"no healthy value exists for {getattr(step, 'tool', '?')}: "
            "the clean run never made this call, so replacement cannot be tested"
        )
    return (
        InterventionSpec(
            kind=InterventionKind.REPLACE_TOOL_RESULT,
            step_id=plan.suspected_step_id,
            replacement=replacement,
            rationale=plan.rationale,
        ),
        "",
    )
