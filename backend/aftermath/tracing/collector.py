"""Trace collection.

The collector owns step-id assignment and the parent chain, so a monitored agent
cannot accidentally produce an invalid trace. It is the single place a step is
created, which is what makes "every tool call and state mutation appears in the
trace" checkable rather than aspirational.

Time is supplied by an injected clock that defaults to a fixed-step counter, not
the wall clock: two runs of the same scenario must produce identical traces, and
`Trace.content_hash()` excludes timestamps precisely so that holds.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from aftermath.companyagent.tools import Mutation, ToolOutcome
from aftermath.core.trace import (
    AgentReasoningStep,
    ApprovalRequestStep,
    FinalOutputStep,
    InjectionInfo,
    NondeterminismRecord,
    NondeterminismSource,
    Outcome,
    PolicyCheckStep,
    StateMutationStep,
    ToolCallStep,
    ToolResultStep,
    Trace,
    TraceStep,
    UserInputStep,
    format_step_id,
)

EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def deterministic_clock() -> Callable[[], datetime]:
    """A clock that advances one second per call, starting at a fixed epoch."""
    counter = {"n": 0}

    def tick() -> datetime:
        moment = EPOCH + timedelta(seconds=counter["n"])
        counter["n"] += 1
        return moment

    return tick


class TraceCollector:
    """Accumulates steps and seals them into a `Trace`."""

    def __init__(
        self,
        *,
        trace_id: str,
        scenario_id: str,
        agent_version: str,
        seed: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.scenario_id = scenario_id
        self.agent_version = agent_version
        self.seed = seed
        self._clock = clock or deterministic_clock()
        self._steps: list[TraceStep] = []
        self._started_at = self._clock()
        self._call_counter = 0

    @property
    def steps(self) -> tuple[TraceStep, ...]:
        return tuple(self._steps)

    def _next_ids(self) -> tuple[str, str | None]:
        ordinal = len(self._steps)
        parent = format_step_id(ordinal - 1) if ordinal else None
        return format_step_id(ordinal), parent

    def next_call_id(self) -> str:
        self._call_counter += 1
        return f"call-{self._call_counter:03d}"

    def _append(self, step: TraceStep) -> str:
        self._steps.append(step)
        return step.step_id

    # ---- step recorders ------------------------------------------------------

    def user_input(self, text: str) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            UserInputStep(step_id=step_id, parent_id=parent, ts=self._clock(), text=text)
        )

    def reasoning(self, thought: str, *, model: str | None = None, record_id: str | None = None) -> str:
        """Record a reasoning step.

        ``record_id`` marks the step as nondeterministic and points replay at the
        recorded model response to reuse instead of re-sampling.
        """
        step_id, parent = self._next_ids()
        return self._append(
            AgentReasoningStep(
                step_id=step_id,
                parent_id=parent,
                ts=self._clock(),
                thought=thought,
                model=model,
                nondeterminism=(
                    NondeterminismRecord(source=NondeterminismSource.LLM, record_id=record_id)
                    if record_id
                    else None
                ),
            )
        )

    def tool_call(self, tool: str, arguments: dict, call_id: str, snapshot_ref: str | None) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            ToolCallStep(
                step_id=step_id,
                parent_id=parent,
                ts=self._clock(),
                tool=tool,
                arguments=arguments,
                call_id=call_id,
                world_snapshot_ref=snapshot_ref,
            )
        )

    def tool_result(self, tool: str, call_id: str, outcome: ToolOutcome) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            ToolResultStep(
                step_id=step_id,
                parent_id=parent,
                ts=self._clock(),
                tool=tool,
                call_id=call_id,
                result=outcome.result,
                error=outcome.error,
            )
        )

    def state_mutation(self, mutation: Mutation) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            StateMutationStep(
                step_id=step_id,
                parent_id=parent,
                ts=self._clock(),
                entity=mutation.entity,
                entity_id=mutation.entity_id,
                before=mutation.before,
                after=mutation.after,
            )
        )

    def policy_check(
        self, policy_id: str, policy_version: str, passed: bool, detail: str | None = None
    ) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            PolicyCheckStep(
                step_id=step_id,
                parent_id=parent,
                ts=self._clock(),
                policy_id=policy_id,
                policy_version=policy_version,
                passed=passed,
                detail=detail,
            )
        )

    def approval_request(self, reason: str, granted: bool, approver: str | None) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            ApprovalRequestStep(
                step_id=step_id,
                parent_id=parent,
                ts=self._clock(),
                reason=reason,
                granted=granted,
                approver=approver,
            )
        )

    def final_output(self, text: str) -> str:
        step_id, parent = self._next_ids()
        return self._append(
            FinalOutputStep(step_id=step_id, parent_id=parent, ts=self._clock(), text=text)
        )

    # ---- sealing -------------------------------------------------------------

    def seal(self, outcome: Outcome, injection: InjectionInfo | None = None) -> Trace:
        """Build the immutable `Trace`. The collector is not reusable afterwards."""
        return Trace(
            trace_id=self.trace_id,
            scenario_id=self.scenario_id,
            agent_version=self.agent_version,
            seed=self.seed,
            injection=injection,
            started_at=self._started_at,
            finished_at=self._clock(),
            outcome=outcome,
            steps=tuple(self._steps),
        )
