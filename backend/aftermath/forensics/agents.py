"""The four MVP runtime agents.

Each is a thin, uniform wrapper: render a versioned prompt, call the provider,
validate the reply against a strict schema. Prompts live in `prompts/` as files
rather than inline strings because they are experimental variables — they must
be diffable, swappable, and attributable when a result changes.

None of these agents decides anything. They propose; `replay/` measures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from aftermath.config import DEFAULT_MODEL
from aftermath.forensics.parsing import AgentOutputError, parse_as
from aftermath.forensics.schemas import (
    InvestigationOutput,
    PlanOutput,
    RepairOutput,
    VerificationOutput,
)
from aftermath.llm.base import LLMProvider, LLMRequest

PROMPT_DIR = Path(__file__).parent / "prompts"
LENS_DIR = PROMPT_DIR / "lenses"

# Ordered so that N investigators always means the same first N lenses — a sweep
# over agent counts must vary the count and nothing else.
LENS_ORDER: tuple[str, ...] = (
    "tool_api",
    "context_memory",
    "state_systems",
    "security_policy",
    "reasoning",
)


def lenses_for(count: int) -> tuple[str | None, ...]:
    """The lenses to run for ``count`` investigators.

    One investigator runs with no lens — the general prompt, exactly as P5/P7
    measured it — so the N=1 arm of a sweep is the existing system rather than a
    new configuration that happens to share its size.
    """
    if count <= 1:
        return (None,)
    if count > len(LENS_ORDER):
        raise ValueError(f"only {len(LENS_ORDER)} lenses defined, asked for {count}")
    return tuple(LENS_ORDER[:count])


def load_lens(name: str) -> str:
    path = LENS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"missing lens prompt: {path}")
    return path.read_text(encoding="utf-8")
T = TypeVar("T", bound=BaseModel)


def load_prompt(name: str) -> str:
    """Read a versioned prompt file.

    Raises:
        FileNotFoundError: if the prompt is missing — a silent empty prompt would
            change results invisibly.
    """
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


class ForensicAgent:
    """Base wrapper: prompt in, validated structured output out."""

    prompt_name: str
    output_model: type[BaseModel]

    def __init__(
        self,
        provider: LLMProvider,
        model: str = DEFAULT_MODEL,
        lens: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._lens = lens

    def _invoke(self, payload: dict[str, Any], output_model: type[T]) -> T:
        system = load_prompt(self.prompt_name)
        tag = f"forensics:{self.prompt_name}"
        if self._lens:
            # Appended, not substituted: every investigator keeps the same base
            # instructions, so a lens changes perspective and nothing else.
            system = f"{system}\n\n---\n\n{load_lens(self._lens)}"
            tag = f"{tag}:{self._lens}"
        request = LLMRequest(
            model=self._model,
            system=system,
            prompt=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            tag=tag,
        )
        response = self._provider.complete(request)
        return parse_as(response.text, output_model)


class Investigator(ForensicAgent):
    """Reads a redacted trace, proposes hypotheses bound to step ids."""

    prompt_name = "investigator"
    output_model = InvestigationOutput

    def investigate(self, redacted_trace: dict[str, Any]) -> InvestigationOutput:
        return self._invoke(redacted_trace, InvestigationOutput)


class CounterfactualPlanner(ForensicAgent):
    """Turns hypotheses into executable interventions.

    Its hardest judgement is the intervention *kind*: a duplicated action needs
    `skip_tool_call`, and choosing `replace_tool_result` there makes the true
    cause undetectable no matter how good the hypothesis was.
    """

    prompt_name = "counterfactual"
    output_model = PlanOutput

    def plan(
        self, hypotheses: list[dict[str, Any]], step_types: dict[str, str]
    ) -> PlanOutput:
        return self._invoke(
            {"hypotheses": hypotheses, "step_types": step_types}, PlanOutput
        )


class RepairAgent(ForensicAgent):
    """Proposes guardrails against the evidenced cause."""

    prompt_name = "repair"
    output_model = RepairOutput

    def propose(self, evidence: dict[str, Any]) -> RepairOutput:
        return self._invoke(evidence, RepairOutput)


class Verifier(ForensicAgent):
    """Critiques the evidence chain and the winning repair."""

    prompt_name = "verifier"
    output_model = VerificationOutput

    def verify(self, measured: dict[str, Any]) -> VerificationOutput:
        return self._invoke(measured, VerificationOutput)


__all__ = [
    "AgentOutputError",
    "CounterfactualPlanner",
    "ForensicAgent",
    "Investigator",
    "RepairAgent",
    "Verifier",
    "load_prompt",
]
