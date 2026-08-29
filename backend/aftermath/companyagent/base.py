"""The monitored-agent boundary.

Everything downstream of this interface consumes traces, never an agent. That is
what lets the monitored system be a custom loop today (D-004), an ADK or
LangGraph agent later, or an external production agent that only ships us JSONL —
without the forensics pipeline knowing or caring.

A conforming agent must:

* be deterministic given the same world seed and scenario,
* record every tool call and every state mutation it causes,
* route all model calls through `LLMProvider` so they can be recorded/replayed,
* perform no real-world side effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from aftermath.companyagent.world import World
from aftermath.core.trace import InjectionInfo, Trace

if TYPE_CHECKING:
    from aftermath.companyagent.scenarios import Scenario


class AgentRun(BaseModel):
    """The result of one monitored run: the trace plus the world it produced."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    trace: Trace
    world: World


@runtime_checkable
class CompanyAgent(Protocol):
    """A monitored agent AFTERMATH can observe."""

    version: str

    def run(
        self,
        scenario: "Scenario",
        world: World,
        injection: InjectionInfo | None = None,
    ) -> AgentRun:
        """Execute ``scenario`` against ``world`` and return the trace and end state.

        ``injection`` is recorded verbatim on the resulting trace. The agent does
        not interpret it: ground truth is authored by the fault injector (D-002),
        and an agent that could see or shape it would corrupt the measurement.
        """
        ...
