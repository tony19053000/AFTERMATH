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

    def __init__(self, provider: LLMProvider, model: str = DEFAULT_MODEL) -> None:
        self._provider = provider
        self._model = model

    def _invoke(self, payload: dict[str, Any], output_model: type[T]) -> T:
        request = LLMRequest(
            model=self._model,
            system=load_prompt(self.prompt_name),
            prompt=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            tag=f"forensics:{self.prompt_name}",
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
