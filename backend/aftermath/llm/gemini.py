"""Gemini provider.

The only place a Gemini SDK may be imported. The SDK is an optional dependency
(`pip install -e "backend[gemini]"`) so the default offline test suite does not
require it, and the import is deferred to call time so merely importing this
module never demands the package or a key.
"""

from __future__ import annotations

import os

from aftermath.config import DEFAULT_MODEL
from aftermath.llm.base import LLMError, LLMRequest, LLMResponse, TokenUsage

API_KEY_ENV = "GEMINI_API_KEY"


class GeminiProvider:
    """Live Gemini access.

    The API key is read from the environment and never logged, never echoed in an
    error message, and never persisted to an artifact.
    """

    name = "gemini"

    def __init__(self, api_key: str | None = None, default_model: str = DEFAULT_MODEL) -> None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise LLMError(
                f"{API_KEY_ENV} is not set. Copy .env.example to .env and add a key, "
                "or use the mock provider (AFTERMATH_LLM_PROVIDER=mock)."
            )
        self._api_key = key
        self._default_model = default_model
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            try:
                from google import genai  # noqa: PLC0415 — deferred: optional dependency
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise LLMError(
                    'google-genai is not installed. Install with: pip install -e "backend[gemini]"'
                ) from exc
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def complete(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        contents = request.prompt
        config: dict[str, object] = {"temperature": request.temperature}
        if request.system:
            config["system_instruction"] = request.system
        if request.max_tokens:
            config["max_output_tokens"] = request.max_tokens

        try:
            result = client.models.generate_content(  # type: ignore[attr-defined]
                model=request.model or self._default_model,
                contents=contents,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001 - normalize any SDK failure
            # The key must never surface in an error path.
            raise LLMError(f"Gemini request failed: {type(exc).__name__}") from exc

        text = getattr(result, "text", None)
        if text is None:
            raise LLMError("Gemini returned no text content")

        usage_meta = getattr(result, "usage_metadata", None)
        usage = TokenUsage(
            prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
        )
        return LLMResponse(text=text, model=request.model, usage=usage)
