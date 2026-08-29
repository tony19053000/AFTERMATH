"""Shared fixtures. Everything here is offline, synthetic, and deterministic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aftermath.config import Settings
from aftermath.core.trace import (
    AgentReasoningStep,
    FinalOutputStep,
    InjectionInfo,
    Outcome,
    OutcomeStatus,
    PolicyCheckStep,
    Severity,
    ToolCallStep,
    ToolResultStep,
    Trace,
    UserInputStep,
    format_step_id,
)
from aftermath.persistence.artifacts import ArtifactStore

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _ts(offset: int) -> datetime:
    return BASE_TIME + timedelta(seconds=offset)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed entirely at a temp directory — never the real data dir."""
    return Settings(
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        artifact_dir=tmp_path / "artifacts",
        seed=1337,
    )


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


def build_trace(
    trace_id: str = "t-0001",
    *,
    injected: bool = True,
    outcome_status: OutcomeStatus = OutcomeStatus.FAIL,
) -> Trace:
    """A small, hand-checkable trace resembling a stale-policy refund incident.

    Synthetic throughout: no real customer, order, or monetary value.
    """
    steps: list[Any] = [
        UserInputStep(
            step_id=format_step_id(0),
            parent_id=None,
            ts=_ts(0),
            text="I want a refund for order ORD-1001.",
        ),
        AgentReasoningStep(
            step_id=format_step_id(1),
            parent_id=format_step_id(0),
            ts=_ts(1),
            thought="Look up the order, then the refund policy.",
            model="mock-model",
            nondeterminism={"source": "llm", "record_id": "llmcall_0001"},
        ),
        ToolCallStep(
            step_id=format_step_id(2),
            parent_id=format_step_id(1),
            ts=_ts(2),
            tool="get_policy",
            arguments={"policy_id": "refund"},
            call_id="call-1",
            world_snapshot_ref="w0002",
        ),
        ToolResultStep(
            step_id=format_step_id(3),
            parent_id=format_step_id(2),
            ts=_ts(3),
            tool="get_policy",
            call_id="call-1",
            result={"policy_id": "refund", "version": "v1", "window_days": 90},
            latency_ms=12.5,
        ),
        PolicyCheckStep(
            step_id=format_step_id(4),
            parent_id=format_step_id(3),
            ts=_ts(4),
            policy_id="refund",
            policy_version="v1",
            passed=True,
            detail="within 90-day window per cached policy",
        ),
        FinalOutputStep(
            step_id=format_step_id(5),
            parent_id=format_step_id(4),
            ts=_ts(5),
            text="Refund approved.",
        ),
    ]

    injection = (
        InjectionInfo(
            kind="stale_policy",
            params={"served_version": "v1", "current_version": "v2"},
            # Ground truth is authored by the injector, never by a model (D-002).
            true_causal_step=format_step_id(3),
            severity=Severity.HIGH,
        )
        if injected
        else None
    )

    return Trace(
        trace_id=trace_id,
        scenario_id="refund_stale_policy_v1",
        agent_version="sim-custops-0.1.0",
        seed=1337,
        injection=injection,
        started_at=_ts(0),
        finished_at=_ts(5),
        outcome=Outcome(
            status=outcome_status,
            oracle="refund_within_current_policy",
            detail="refund granted under superseded policy v1",
        ),
        steps=tuple(steps),
    )


@pytest.fixture
def sample_trace() -> Trace:
    return build_trace()
