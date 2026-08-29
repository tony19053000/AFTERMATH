"""Provider construction — the single place provider choice is resolved."""

from __future__ import annotations

from pathlib import Path

from aftermath.config import LLMProviderName, Settings
from aftermath.llm.base import LLMProvider
from aftermath.llm.mock import MockProvider
from aftermath.llm.recording import RecordingProvider, RecordMode


def build_provider(
    settings: Settings,
    cassette_path: Path | None = None,
    mode: RecordMode = RecordMode.RECORD,
) -> LLMProvider:
    """Build the configured provider, wrapped for recording when enabled."""
    inner: LLMProvider
    match settings.llm_provider:
        case LLMProviderName.MOCK:
            inner = MockProvider()
        case LLMProviderName.GEMINI:
            # Imported here so the default (mock) path never requires the SDK.
            from aftermath.llm.gemini import GeminiProvider  # noqa: PLC0415

            inner = GeminiProvider(default_model=settings.baseline_model)
        case _:  # pragma: no cover - StrEnum is exhaustive
            raise ValueError(f"unknown provider {settings.llm_provider!r}")

    if not settings.record_llm_calls:
        return inner

    path = cassette_path or (settings.artifact_dir / "cassettes" / f"{inner.name}.json")
    return RecordingProvider(inner, cassette_path=path, mode=mode)
