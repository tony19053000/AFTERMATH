"""The single-LLM baseline.

**This is the only module in `benchmark/` permitted to call a model** — it is an
LLM by definition (D-007). The grader, metrics, and runner beside it are strictly
deterministic, and the import-boundary test enforces that separation.

Fairness is a methodology commitment, not a courtesy. The baseline receives:

* the **same** redacted trace AFTERMATH's investigator receives,
* the **same** output schema,
* the **same** model,
* a genuinely well-written prompt.

What it does not receive is counterfactual replay, a swarm, or experimental
verification — because those are the system under test. A strawman baseline
would invalidate the entire comparison, and a reviewer would spot it instantly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aftermath.config import DEFAULT_MODEL
from aftermath.forensics.parsing import AgentOutputError, parse_as
from aftermath.forensics.redaction import redact_for_agent
from aftermath.llm.base import LLMProvider, LLMRequest

PROMPT_PATH = Path(__file__).parent / "prompts" / "baseline.md"


class BaselineDiagnosis(BaseModel):
    """The baseline's answer, in the same shape AFTERMATH must produce."""

    model_config = ConfigDict(extra="forbid")

    root_cause_step_id: str = Field(min_length=1)
    mechanism: str = ""
    evidence: str = ""
    recommended_fix: str = ""


class BaselineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    diagnosis: BaselineDiagnosis | None = None
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def answered(self) -> bool:
        return self.diagnosis is not None


def diagnose(
    provider: LLMProvider,
    incident_id: str,
    trace: Any,
    model: str = DEFAULT_MODEL,
) -> BaselineResult:
    """Ask one capable model to diagnose the failure, unaided.

    Never raises on a bad answer: an unparseable reply is a real outcome for this
    system and is recorded as one, exactly as a failed AFTERMATH agent would be.
    """
    request = LLMRequest(
        model=model,
        system=PROMPT_PATH.read_text(encoding="utf-8"),
        prompt=_serialize(redact_for_agent(trace)),
        tag=f"baseline:{incident_id}",
    )
    try:
        response = provider.complete(request)
    except Exception as exc:  # noqa: BLE001 - a provider failure is a recorded outcome
        return BaselineResult(incident_id=incident_id, error=f"provider: {type(exc).__name__}")

    try:
        diagnosis = parse_as(response.text, BaselineDiagnosis)
    except AgentOutputError as exc:
        return BaselineResult(
            incident_id=incident_id,
            error=str(exc)[:200],
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )
    return BaselineResult(
        incident_id=incident_id,
        diagnosis=diagnosis,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )


def _serialize(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
