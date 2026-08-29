"""Trace schema, round-tripping, and hash stability.

P1 acceptance: a trace round-trips model -> JSONL -> model with an identical
content hash.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from aftermath.core.trace import (
    FinalOutputStep,
    Outcome,
    OutcomeStatus,
    Trace,
    UserInputStep,
    format_step_id,
)
from tests.conftest import BASE_TIME, build_trace


class TestRoundTrip:
    def test_roundtrip_preserves_content_and_hash(self, sample_trace: Trace) -> None:
        restored = Trace.from_jsonl(sample_trace.to_jsonl())

        assert restored == sample_trace
        assert restored.content_hash() == sample_trace.content_hash()

    def test_roundtrip_is_byte_stable(self, sample_trace: Trace) -> None:
        once = sample_trace.to_jsonl()
        twice = Trace.from_jsonl(once).to_jsonl()

        assert once == twice

    def test_jsonl_is_line_oriented(self, sample_trace: Trace) -> None:
        lines = sample_trace.to_jsonl().strip().splitlines()

        # One envelope line plus one line per step.
        assert len(lines) == 1 + len(sample_trace.steps)

    def test_step_lookup(self, sample_trace: Trace) -> None:
        assert sample_trace.step("s0003").step_id == "s0003"
        with pytest.raises(KeyError):
            sample_trace.step("s9999")


class TestContentHash:
    def test_identical_content_hashes_identically(self) -> None:
        assert build_trace("t-a").content_hash() == build_trace("t-b").content_hash()

    def test_hash_ignores_wall_clock(self, sample_trace: Trace) -> None:
        """Same content at a different time must hash the same.

        P4 verifies replay fidelity by comparing hashes; a clock-sensitive hash
        would make that check meaningless.
        """
        shifted = sample_trace.model_copy(
            update={
                "started_at": sample_trace.started_at + timedelta(days=5),
                "finished_at": sample_trace.finished_at + timedelta(days=5),
            }
        )

        assert shifted.content_hash() == sample_trace.content_hash()

    def test_hash_detects_changed_step(self, sample_trace: Trace) -> None:
        mutated = list(sample_trace.steps)
        mutated[-1] = FinalOutputStep(
            step_id=format_step_id(5),
            parent_id=format_step_id(4),
            ts=mutated[-1].ts,
            text="Refund denied.",
        )
        changed = sample_trace.model_copy(update={"steps": tuple(mutated)})

        assert changed.content_hash() != sample_trace.content_hash()

    def test_hash_detects_changed_outcome(self, sample_trace: Trace) -> None:
        changed = sample_trace.model_copy(
            update={"outcome": Outcome(status=OutcomeStatus.PASS, oracle="x")}
        )

        assert changed.content_hash() != sample_trace.content_hash()

    def test_tampered_jsonl_is_rejected(self, sample_trace: Trace) -> None:
        tampered = sample_trace.to_jsonl().replace("Refund approved.", "Refund denied!")

        with pytest.raises(ValueError, match="content hash mismatch"):
            Trace.from_jsonl(tampered)


class TestStepValidation:
    """Step ids are load-bearing: hypotheses and interventions address steps by id."""

    def _envelope(self, steps: tuple) -> dict:
        return {
            "trace_id": "t",
            "scenario_id": "s",
            "agent_version": "v",
            "seed": 1,
            "started_at": BASE_TIME,
            "finished_at": BASE_TIME,
            "outcome": {"status": "PASS", "oracle": "o"},
            "steps": steps,
        }

    def test_rejects_non_ordinal_step_ids(self) -> None:
        steps = (
            UserInputStep(step_id="s0000", ts=BASE_TIME, text="hi"),
            FinalOutputStep(step_id="s0007", parent_id="s0000", ts=BASE_TIME, text="bye"),
        )
        with pytest.raises(ValidationError, match="ordinal and stable"):
            Trace.model_validate(self._envelope(steps))

    def test_rejects_unknown_parent(self) -> None:
        steps = (
            UserInputStep(step_id="s0000", ts=BASE_TIME, text="hi"),
            FinalOutputStep(step_id="s0001", parent_id="s0099", ts=BASE_TIME, text="bye"),
        )
        with pytest.raises(ValidationError, match="unknown parent"):
            Trace.model_validate(self._envelope(steps))

    def test_rejects_missing_parent_on_later_step(self) -> None:
        steps = (
            UserInputStep(step_id="s0000", ts=BASE_TIME, text="hi"),
            FinalOutputStep(step_id="s0001", ts=BASE_TIME, text="bye"),
        )
        with pytest.raises(ValidationError, match="must declare a parent"):
            Trace.model_validate(self._envelope(steps))

    def test_rejects_finished_before_started(self) -> None:
        envelope = self._envelope(())
        envelope["finished_at"] = BASE_TIME - timedelta(seconds=1)
        with pytest.raises(ValidationError, match="precedes started_at"):
            Trace.model_validate(envelope)

    def test_rejects_ground_truth_pointing_outside_trace(self) -> None:
        envelope = self._envelope((UserInputStep(step_id="s0000", ts=BASE_TIME, text="hi"),))
        envelope["injection"] = {"kind": "k", "true_causal_step": "s0042"}
        with pytest.raises(ValidationError, match="not a step in this trace"):
            Trace.model_validate(envelope)

    def test_trace_is_immutable(self, sample_trace: Trace) -> None:
        """Traces are evidence; they are not edited in place."""
        with pytest.raises(ValidationError):
            sample_trace.scenario_id = "something-else"  # type: ignore[misc]

    def test_unknown_field_rejected(self) -> None:
        envelope = self._envelope(())
        envelope["surprise"] = 1
        with pytest.raises(ValidationError):
            Trace.model_validate(envelope)


class TestGroundTruthProvenance:
    """Ground truth must originate from the injector, never from a model (D-002)."""

    def test_ground_truth_lives_on_injection_not_on_agent_steps(
        self, sample_trace: Trace
    ) -> None:
        assert sample_trace.injection is not None
        assert sample_trace.injection.true_causal_step == "s0003"

        # No step type carries a ground-truth field an agent could populate.
        for step in sample_trace.steps:
            fields = set(type(step).model_fields)
            assert not fields & {"true_causal_step", "root_cause", "is_cause"}

    def test_clean_trace_has_no_injection(self) -> None:
        assert build_trace(injected=False).injection is None


class TestMalformedInput:
    def test_empty_document_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty trace document"):
            Trace.from_jsonl("")

    def test_missing_envelope_marker_rejected(self, sample_trace: Trace) -> None:
        body = sample_trace.to_jsonl().splitlines()[1:]
        with pytest.raises(ValueError, match="not a trace envelope"):
            Trace.from_jsonl("\n".join(body))

    def test_negative_step_ordinal_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            format_step_id(-1)
