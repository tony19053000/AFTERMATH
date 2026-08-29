"""Deterministic offline provider.

This is the default for tests and local development. Given the same request it
returns the same response, always, with no network. That makes the whole default
test suite reproducible (`docs/TESTING.md` §1).
"""

from __future__ import annotations

import hashlib

from aftermath.llm.base import LLMRequest, LLMResponse, TokenUsage


class MockProvider:
    """Derives a stable pseudo-response from a hash of the request.

    Scripted replies can be supplied for tests that need specific content:
    responses are matched by ``LLMRequest.tag`` first, then by full cache key.
    """

    name = "mock"

    def __init__(self, scripted: dict[str, str] | None = None) -> None:
        self._scripted = dict(scripted or {})

    def script(self, key: str, text: str) -> None:
        """Pin a response for a request tag or cache key."""
        self._scripted[key] = text

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request.cache_key()
        if request.tag is not None and request.tag in self._scripted:
            text = self._scripted[request.tag]
        elif key in self._scripted:
            text = self._scripted[key]
        else:
            text = self._synthesize(request)

        # Deterministic, clearly-fake usage figures. Any real token accounting
        # must come from a real provider; these must never reach a report.
        return LLMResponse(
            text=text,
            model=request.model,
            usage=TokenUsage(
                prompt_tokens=len(request.prompt.split()),
                completion_tokens=len(text.split()),
            ),
        )

    @staticmethod
    def _synthesize(request: LLMRequest) -> str:
        digest = hashlib.sha256(request.cache_key().encode("utf-8")).hexdigest()
        return f"[mock:{request.model}] {digest[:16]}"
