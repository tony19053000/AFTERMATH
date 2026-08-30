"""Gemini provider — a direct REST client.

**Why not the vendor SDK.** `google-genai` was used first and hung
indefinitely on ordinary requests: zero CPU, no error, no timeout honoured at
the socket level, while the identical payload returned HTTP 200 in ~11s over
plain HTTPS. A provider that can stall a benchmark run with no diagnostic is
not acceptable in the one layer everything else depends on.

This is ~60 lines of stdlib `urllib`. It adds no runtime dependency, gives
exact control over timeouts and retries, and keeps D-006's promise that
swapping providers touches one file. The SDK remains an optional extra for
anyone who wants it.

The API key is read from the environment and never logged, never echoed in an
error message, and never persisted to an artifact.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from aftermath.config import DEFAULT_MODEL
from aftermath.llm.base import LLMError, LLMRequest, LLMResponse, TokenUsage

API_KEY_ENV = "GEMINI_API_KEY"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# A stalled request must become an error, not an indefinite wait.
REQUEST_TIMEOUT_SECONDS = 90.0
# Transient 5xx responses are common enough on long runs that one should not end
# a 20-incident benchmark. Bounded: a persistent failure still surfaces.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class GeminiProvider:
    """Live Gemini access over the REST API."""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_MODEL,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise LLMError(
                f"{API_KEY_ENV} is not set. Copy .env.example to .env and add a key, "
                "or use the mock provider (AFTERMATH_LLM_PROVIDER=mock)."
            )
        self._api_key = key
        self._default_model = default_model
        self._timeout = timeout_seconds

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._default_model
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": request.prompt}]}],
            "generationConfig": {"temperature": request.temperature},
        }
        if request.system:
            body["system_instruction"] = {"parts": [{"text": request.system}]}
        if request.max_tokens:
            body["generationConfig"]["maxOutputTokens"] = request.max_tokens

        payload = self._post(model, body)
        return self._to_response(payload, model)

    def _post(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST with bounded retries.

        Raises:
            LLMError: on a non-retryable status, or after exhausting retries.
                The key is never included in the message.
        """
        url = f"{API_ROOT}/{model}:generateContent"
        data = json.dumps(body).encode("utf-8")
        last: str = "unknown"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            http_request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self._api_key,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(  # noqa: S310 - fixed https endpoint
                    http_request, timeout=self._timeout
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in RETRYABLE_STATUS:
                    raise LLMError(f"Gemini request rejected: {last}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = type(exc).__name__
            except json.JSONDecodeError:
                raise LLMError("Gemini returned a non-JSON body") from None

            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        raise LLMError(f"Gemini request failed after {MAX_ATTEMPTS} attempts: {last}")

    @staticmethod
    def _to_response(payload: dict[str, Any], model: str) -> LLMResponse:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Gemini returned no candidate content") from None

        text = "".join(part.get("text", "") for part in parts)
        if not text:
            raise LLMError("Gemini returned empty text")

        usage = payload.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=model,
            usage=TokenUsage(
                prompt_tokens=usage.get("promptTokenCount", 0) or 0,
                completion_tokens=usage.get("candidatesTokenCount", 0) or 0,
            ),
        )
