"""Trace schema — the interchange format between a monitored agent and AFTERMATH.

Design constraints that later phases depend on:

* ``step_id`` is stable and ordinal. Hypotheses and interventions address steps
  by ID, so instability here would break causal localization (P4/P5).
* Every nondeterministic step carries a ``nondeterminism`` record reference, so
  replay can reproduce it from the record instead of re-sampling (P4).
* ``world_snapshot_ref`` lets replay restore state and branch from any step.
* The schema is agent-framework-agnostic. An external agent integrates by
  emitting this format — nothing here assumes Google ADK or an in-process agent.

Semantic hashing excludes wall-clock fields (``ts``, ``started_at``,
``finished_at``) so that the same scenario replayed with the same seed hashes
identically. That property is what P4 asserts against.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aftermath.core.hashing import canonical_json, content_hash

STEP_ID_PREFIX = "s"
STEP_ID_WIDTH = 4


def format_step_id(ordinal: int) -> str:
    """Build a stable step id from its ordinal position (``0`` -> ``s0000``)."""
    if ordinal < 0:
        raise ValueError(f"step ordinal must be non-negative, got {ordinal}")
    return f"{STEP_ID_PREFIX}{ordinal:0{STEP_ID_WIDTH}d}"


class StepType(StrEnum):
    USER_INPUT = "user_input"
    AGENT_REASONING = "agent_reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE_MUTATION = "state_mutation"
    POLICY_CHECK = "policy_check"
    APPROVAL_REQUEST = "approval_request"
    FINAL_OUTPUT = "final_output"


class OutcomeStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class NondeterminismSource(StrEnum):
    LLM = "llm"
    RANDOM = "random"
    CLOCK = "clock"
    EXTERNAL = "external"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class _Frozen(BaseModel):
    """Traces are evidence: once recorded, they are not edited in place."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NondeterminismRecord(_Frozen):
    """Points a nondeterministic step at the recorded value replay should reuse."""

    source: NondeterminismSource
    record_id: str = Field(min_length=1)


class _StepBase(_Frozen):
    step_id: str = Field(pattern=rf"^{STEP_ID_PREFIX}\d{{{STEP_ID_WIDTH},}}$")
    parent_id: str | None = None
    ts: datetime
    world_snapshot_ref: str | None = None
    nondeterminism: NondeterminismRecord | None = None


class UserInputStep(_StepBase):
    type: Literal[StepType.USER_INPUT] = StepType.USER_INPUT
    text: str


class AgentReasoningStep(_StepBase):
    type: Literal[StepType.AGENT_REASONING] = StepType.AGENT_REASONING
    thought: str
    model: str | None = None


class ToolCallStep(_StepBase):
    type: Literal[StepType.TOOL_CALL] = StepType.TOOL_CALL
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(min_length=1)


class ToolResultStep(_StepBase):
    type: Literal[StepType.TOOL_RESULT] = StepType.TOOL_RESULT
    tool: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    result: Any = None
    error: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class StateMutationStep(_StepBase):
    type: Literal[StepType.STATE_MUTATION] = StepType.STATE_MUTATION
    entity: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    before: Any = None
    after: Any = None


class PolicyCheckStep(_StepBase):
    type: Literal[StepType.POLICY_CHECK] = StepType.POLICY_CHECK
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    passed: bool
    detail: str | None = None


class ApprovalRequestStep(_StepBase):
    type: Literal[StepType.APPROVAL_REQUEST] = StepType.APPROVAL_REQUEST
    reason: str
    granted: bool
    approver: str | None = None


class FinalOutputStep(_StepBase):
    type: Literal[StepType.FINAL_OUTPUT] = StepType.FINAL_OUTPUT
    text: str


TraceStep = Annotated[
    UserInputStep
    | AgentReasoningStep
    | ToolCallStep
    | ToolResultStep
    | StateMutationStep
    | PolicyCheckStep
    | ApprovalRequestStep
    | FinalOutputStep,
    Field(discriminator="type"),
]


class InjectionInfo(_Frozen):
    """What the fault injector did, and the ground truth it therefore knows.

    Ground truth originates here — from the controlled injection — and never from
    a model. `docs/DECISIONS.md` D-002.
    """

    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    true_causal_step: str | None = None
    severity: Severity | None = None


class Outcome(_Frozen):
    """Result of a run, decided by the scenario oracle in Python — never by a model."""

    status: OutcomeStatus
    oracle: str = Field(min_length=1)
    detail: str | None = None


class Trace(_Frozen):
    """A complete agent run: envelope plus ordered steps."""

    trace_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    seed: int
    injection: InjectionInfo | None = None
    started_at: datetime
    finished_at: datetime
    outcome: Outcome
    steps: tuple[TraceStep, ...] = ()

    @model_validator(mode="after")
    def _validate_step_sequence(self) -> Self:
        seen: set[str] = set()
        for index, step in enumerate(self.steps):
            expected = format_step_id(index)
            if step.step_id != expected:
                raise ValueError(
                    f"step {index} has id {step.step_id!r}, expected {expected!r}: "
                    "step ids must be ordinal and stable"
                )
            if step.step_id in seen:
                raise ValueError(f"duplicate step_id {step.step_id!r}")
            if step.parent_id is not None and step.parent_id not in seen:
                raise ValueError(
                    f"step {step.step_id!r} references unknown parent {step.parent_id!r}"
                )
            if index > 0 and step.parent_id is None:
                raise ValueError(f"step {step.step_id!r} must declare a parent")
            if index == 0 and step.parent_id is not None:
                raise ValueError("first step must not declare a parent")
            seen.add(step.step_id)
        if self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")
        if self.injection is not None:
            true_step = self.injection.true_causal_step
            if true_step is not None and self.steps and true_step not in seen:
                raise ValueError(
                    f"injection.true_causal_step {true_step!r} is not a step in this trace"
                )
        return self

    def step(self, step_id: str) -> TraceStep:
        """Look up a step by id.

        Raises:
            KeyError: if no such step exists.
        """
        for candidate in self.steps:
            if candidate.step_id == step_id:
                return candidate
        raise KeyError(f"no step {step_id!r} in trace {self.trace_id!r}")

    def semantic_payload(self) -> dict[str, Any]:
        """The content that defines this trace's identity.

        Wall-clock fields are excluded so that the same scenario replayed with the
        same seed produces the same hash. ``trace_id`` is excluded for the same
        reason: it identifies the run, not the content.
        """
        return {
            "scenario_id": self.scenario_id,
            "agent_version": self.agent_version,
            "seed": self.seed,
            "injection": self.injection.model_dump(mode="json") if self.injection else None,
            "outcome": self.outcome.model_dump(mode="json"),
            "steps": [
                {k: v for k, v in step.model_dump(mode="json").items() if k != "ts"}
                for step in self.steps
            ],
        }

    def content_hash(self) -> str:
        """Stable hash over semantic content. Identical content, identical hash."""
        return content_hash(self.semantic_payload())

    # ---- JSONL serialization -------------------------------------------------
    # Envelope on the first line, one step per line after it. Line-oriented so a
    # long trace can be streamed and appended to during a run.

    def to_jsonl(self) -> str:
        envelope = self.model_dump(mode="json", exclude={"steps"})
        envelope["_record"] = "envelope"
        envelope["content_hash"] = self.content_hash()
        lines = [canonical_line(envelope)]
        lines.extend(canonical_line(step.model_dump(mode="json")) for step in self.steps)
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jsonl(cls, text: str) -> Trace:
        """Parse a JSONL trace.

        Raises:
            ValueError: if the document is empty, malformed, or its recorded
                content hash does not match the parsed content.
        """
        raw_lines = [line for line in text.splitlines() if line.strip()]
        if not raw_lines:
            raise ValueError("empty trace document")

        envelope = json.loads(raw_lines[0])
        if envelope.pop("_record", None) != "envelope":
            raise ValueError("first line is not a trace envelope")
        recorded_hash = envelope.pop("content_hash", None)

        envelope["steps"] = [json.loads(line) for line in raw_lines[1:]]
        trace = cls.model_validate(envelope)

        if recorded_hash is not None and recorded_hash != trace.content_hash():
            raise ValueError(
                f"trace content hash mismatch: recorded {recorded_hash}, "
                f"computed {trace.content_hash()} — the trace was altered"
            )
        return trace


def canonical_line(payload: dict[str, Any]) -> str:
    """One canonical JSON line, for JSONL output."""
    return canonical_json(payload)
