"""Provider determinism and record/replay.

P1 acceptance: the mock provider is deterministic, and a recorded call replays
byte-identically with no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aftermath.config import LLMProviderName, Settings
from aftermath.llm.base import LLMRequest, LLMResponse, RecordingMissError, TokenUsage
from aftermath.llm.factory import build_provider
from aftermath.llm.mock import MockProvider
from aftermath.llm.recording import RecordingProvider, RecordMode


def make_request(prompt: str = "why did step 7 fail?", tag: str | None = None) -> LLMRequest:
    return LLMRequest(model="test-model", prompt=prompt, tag=tag)


class TestMockDeterminism:
    def test_same_request_same_response(self) -> None:
        provider = MockProvider()
        request = make_request()

        assert provider.complete(request).text == provider.complete(request).text

    def test_independent_instances_agree(self) -> None:
        request = make_request()

        assert MockProvider().complete(request).text == MockProvider().complete(request).text

    def test_different_requests_differ(self) -> None:
        provider = MockProvider()

        assert provider.complete(make_request("a")).text != provider.complete(
            make_request("b")
        ).text

    def test_scripted_response_by_tag(self) -> None:
        provider = MockProvider(scripted={"investigate": "step 3 is the cause"})

        assert provider.complete(make_request(tag="investigate")).text == "step 3 is the cause"

    def test_cache_key_ignores_field_order(self) -> None:
        a = LLMRequest(model="m", prompt="p", temperature=0.0, tag="t")
        b = LLMRequest(tag="t", temperature=0.0, prompt="p", model="m")

        assert a.cache_key() == b.cache_key()


class _CountingProvider:
    """Records how many live calls were made, so we can prove replay is offline."""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text=f"live-{self.calls}",
            model=request.model,
            usage=TokenUsage(prompt_tokens=3, completion_tokens=5),
        )


class TestRecordReplay:
    def test_records_then_serves_without_calling_provider(self, tmp_path: Path) -> None:
        inner = _CountingProvider()
        cassette = tmp_path / "cassette.json"
        recorder = RecordingProvider(inner, cassette, RecordMode.RECORD)
        request = make_request()

        first = recorder.complete(request)
        second = recorder.complete(request)

        assert inner.calls == 1, "second call must be served from the cassette"
        assert first.text == second.text

    def test_replay_is_byte_identical_and_offline(self, tmp_path: Path) -> None:
        cassette = tmp_path / "cassette.json"
        inner = _CountingProvider()
        request = make_request()
        recorded = RecordingProvider(inner, cassette, RecordMode.RECORD).complete(request)

        # No inner provider at all: any network attempt would be impossible.
        replayer = RecordingProvider(None, cassette, RecordMode.REPLAY)
        replayed = replayer.complete(request)

        assert replayed.text == recorded.text
        assert replayed.model == recorded.model
        assert replayed.usage == recorded.usage
        assert replayed.from_record is True

    def test_replay_miss_raises_rather_than_going_live(self, tmp_path: Path) -> None:
        """A silent live fallback would destroy reproducibility."""
        cassette = tmp_path / "cassette.json"
        inner = _CountingProvider()
        RecordingProvider(inner, cassette, RecordMode.RECORD).complete(make_request("recorded"))

        replayer = RecordingProvider(inner, cassette, RecordMode.REPLAY)

        with pytest.raises(RecordingMissError, match="must not fall back"):
            replayer.complete(make_request("never recorded"))
        assert inner.calls == 1, "replay must not have invoked the live provider"

    def test_record_mode_requires_inner_provider(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="requires an inner provider"):
            RecordingProvider(None, tmp_path / "c.json", RecordMode.RECORD)

    def test_cassette_persists_across_instances(self, tmp_path: Path) -> None:
        cassette = tmp_path / "cassette.json"
        request = make_request()
        RecordingProvider(_CountingProvider(), cassette, RecordMode.RECORD).complete(request)

        reopened = RecordingProvider(None, cassette, RecordMode.REPLAY)

        assert len(reopened.cassette) == 1
        assert reopened.complete(request).from_record is True


class TestFactory:
    def test_mock_is_default_and_wrapped_for_recording(self, tmp_path: Path) -> None:
        settings = Settings(artifact_dir=tmp_path)
        provider = build_provider(settings, cassette_path=tmp_path / "c.json")

        assert isinstance(provider, RecordingProvider)
        assert settings.llm_provider is LLMProviderName.MOCK

    def test_recording_can_be_disabled(self, tmp_path: Path) -> None:
        settings = Settings(artifact_dir=tmp_path, record_llm_calls=False)

        assert isinstance(build_provider(settings), MockProvider)
