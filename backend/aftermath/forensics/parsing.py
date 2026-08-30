"""Turning model text into validated objects, or failing cleanly.

Models emit prose, fences, and preambles around JSON. This extracts the JSON and
validates it. When that is impossible it raises `AgentOutputError` rather than
guessing: a pipeline that silently invents structure from unparseable output is
worse than one that reports the agent failed.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AgentOutputError(ValueError):
    """The agent's output could not be parsed or did not validate."""


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of model output.

    Raises:
        AgentOutputError: if no JSON object can be recovered.
    """
    for candidate in _candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AgentOutputError(f"no JSON object found in agent output: {text[:160]!r}")


def _candidates(text: str) -> list[str]:
    found = [match.group(1).strip() for match in _FENCE.finditer(text)]
    stripped = text.strip()
    found.append(stripped)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        found.append(stripped[start : end + 1])
    return found


def parse_as(text: str, model: type[T]) -> T:
    """Parse model output into ``model``.

    Raises:
        AgentOutputError: on unparseable or non-conforming output.
    """
    payload = extract_json(text)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise AgentOutputError(f"{model.__name__} validation failed: {exc.error_count()} errors")
