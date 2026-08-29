"""Record/replay wrapper for model calls.

Reproducibility is the point. A recorded run can be replayed offline and
byte-identically, which is what lets P4 verify replay fidelity and what lets any
published result be re-derived from stored artifacts.

Two modes:

* ``RECORD`` — call the wrapped provider, persist every response.
* ``REPLAY`` — serve from the cassette only. A missing recording raises
  `RecordingMissError` rather than falling back to a live call; a replay that
  silently re-samples is not a replay.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from aftermath.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    RecordingMissError,
)


class RecordMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"


class Cassette:
    """A keyed store of recorded responses, persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, dict[str, object]] = {}
        if path.exists():
            self._entries = json.loads(path.read_text(encoding="utf-8"))

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> LLMResponse | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        return LLMResponse.model_validate({**entry, "from_record": True})

    def put(self, key: str, response: LLMResponse) -> None:
        self._entries[key] = response.model_dump(mode="json", exclude={"from_record"})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Sorted keys keep cassettes diffable and stable across runs.
        self.path.write_text(
            json.dumps(self._entries, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )


class RecordingProvider:
    """Wraps a provider to record responses, or to serve them without a network."""

    def __init__(
        self,
        inner: LLMProvider | None,
        cassette_path: Path,
        mode: RecordMode = RecordMode.RECORD,
    ) -> None:
        if mode is RecordMode.RECORD and inner is None:
            raise ValueError("record mode requires an inner provider to record from")
        self._inner = inner
        self._mode = mode
        self._cassette = Cassette(cassette_path)
        self.name = f"recording({inner.name if inner else 'replay-only'})"

    @property
    def cassette(self) -> Cassette:
        return self._cassette

    @property
    def mode(self) -> RecordMode:
        return self._mode

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request.cache_key()
        recorded = self._cassette.get(key)
        if recorded is not None:
            return recorded

        if self._mode is RecordMode.REPLAY:
            raise RecordingMissError(
                f"no recording for request tag={request.tag!r} model={request.model!r} "
                f"(key {key}). Replay must not fall back to a live call — "
                "re-record the cassette instead."
            )

        assert self._inner is not None  # guaranteed by __init__ in RECORD mode
        response = self._inner.complete(request)
        self._cassette.put(key, response)
        self._cassette.save()
        return response
