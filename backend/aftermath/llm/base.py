"""LLM provider abstraction.

No vendor SDK may be imported outside this package and `companyagent`. Swapping
providers must touch exactly one file (`docs/DECISIONS.md` D-006).

Nothing in `replay/` or `immunity/` may import this module — deterministic
evidence never depends on a model. Enforced by `tests/arch/test_import_boundaries.py`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class LLMRequest(BaseModel):
    """A single completion request. Hashed to key recorded responses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1)
    prompt: str
    system: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    # Distinguishes otherwise-identical calls made at different pipeline stages,
    # so recordings stay unambiguous.
    tag: str | None = None

    def cache_key(self) -> str:
        from aftermath.core.hashing import content_hash

        return content_hash(self.model_dump(mode="json"))


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str = Field(min_length=1)
    usage: TokenUsage = TokenUsage()
    # True when served from a recording rather than a live call. Reports must be
    # able to state honestly how a result was produced.
    from_record: bool = False


class LLMError(RuntimeError):
    """Provider call failed."""


class RecordingMissError(LLMError):
    """Strict replay needed a recorded response and none existed.

    Raised rather than silently falling back to a live call: a replay that
    quietly re-samples is no longer reproducible, and would invalidate any
    evidence built on it.
    """


@runtime_checkable
class LLMProvider(Protocol):
    """The only interface the rest of the system may use to reach a model."""

    name: str

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a completion for ``request``.

        Raises:
            LLMError: on provider failure.
        """
        ...
