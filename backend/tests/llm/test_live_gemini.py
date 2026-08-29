"""Hermeticity guards, and opt-in live-provider checks.

The hermeticity tests are the important ones and always run: a suite whose
result depends on an untracked local file is not a suite, and a stray API key on
a developer's machine must never silently turn "offline, deterministic" tests
into billed network calls.

The `live` tests are excluded by default (`addopts = -m 'not live'`). Run them
deliberately with `pytest backend/tests -m live`, which requires GEMINI_API_KEY.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aftermath.config import DEFAULT_MODEL, LLMProviderName, Settings, get_settings
from aftermath.llm.base import LLMRequest
from aftermath.llm.factory import build_provider
from aftermath.llm.recording import RecordingProvider, RecordMode

REPO_ENV = Path(__file__).resolve().parents[3] / ".env"


class TestHermeticity:
    def test_settings_ignore_a_local_env_file(self) -> None:
        """Even when a real .env exists on disk, the suite sees the shipped defaults."""
        settings = get_settings()

        assert settings.llm_provider is LLMProviderName.MOCK
        assert settings.baseline_model == DEFAULT_MODEL

    def test_default_provider_is_offline(self, tmp_path: Path) -> None:
        provider = build_provider(Settings(artifact_dir=tmp_path), cassette_path=tmp_path / "c")

        assert isinstance(provider, RecordingProvider)
        assert "mock" in provider.name

    def test_no_api_key_is_visible_to_tests(self) -> None:
        assert os.environ.get("GEMINI_API_KEY") is None

    def test_agent_and_baseline_models_match_by_default(self) -> None:
        """Baseline fairness (D-007): equal capability on both sides.

        If these ever diverge by default, the benchmark stops measuring the
        engineering system and starts measuring the model gap.
        """
        settings = get_settings()

        assert settings.agent_model == settings.baseline_model

    def test_env_file_is_not_tracked_by_git(self) -> None:
        """A local .env may exist; it must never be committable."""
        gitignore = (Path(__file__).resolve().parents[3] / ".gitignore").read_text()

        assert "\n.env\n" in gitignore


@pytest.mark.live
class TestLiveGemini:
    """Real calls against the configured provider. Opt-in, billed, needs a key."""

    @pytest.fixture
    def live_settings(self) -> Settings:
        if not os.environ.get("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set; run with the key exported")
        return Settings(llm_provider=LLMProviderName.GEMINI)

    def test_live_call_returns_text_and_usage(self, live_settings: Settings, tmp_path: Path) -> None:
        provider = build_provider(live_settings, cassette_path=tmp_path / "c.json")

        response = provider.complete(
            LLMRequest(
                model=live_settings.agent_model,
                prompt="Reply with exactly one word: ready",
                tag="live-smoke",
            )
        )

        assert response.text.strip()
        assert response.usage.total_tokens > 0

    def test_live_call_records_and_replays_offline(
        self, live_settings: Settings, tmp_path: Path
    ) -> None:
        """The P1 record/replay guarantee, verified against a real model.

        This is what makes a benchmark run reproducible after the fact: the
        recording replays byte-identically with no provider instance at all.
        """
        cassette = tmp_path / "c.json"
        request = LLMRequest(
            model=live_settings.agent_model,
            prompt="Name the capital of France in one word.",
            tag="live-replay",
        )

        live = build_provider(live_settings, cassette_path=cassette).complete(request)
        replayed = RecordingProvider(None, cassette, RecordMode.REPLAY).complete(request)

        assert replayed.text == live.text
        assert replayed.usage == live.usage
        assert live.from_record is False
        assert replayed.from_record is True

    def test_configured_model_is_reachable(self, live_settings: Settings, tmp_path: Path) -> None:
        """Guards against a pinned model name that no longer exists.

        `gemini-2.5-pro` was configured at first and returned 404 on this key;
        this test is why that is now caught rather than discovered mid-benchmark.
        """
        provider = build_provider(live_settings, cassette_path=tmp_path / "c.json")

        response = provider.complete(
            LLMRequest(model=live_settings.baseline_model, prompt="Say: ok", tag="reachable")
        )

        assert response.model == live_settings.baseline_model
        assert response.text.strip()
