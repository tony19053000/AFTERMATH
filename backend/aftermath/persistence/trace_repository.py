"""Trace persistence: JSONL artifact on disk, indexed row in SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aftermath.core.trace import Trace
from aftermath.persistence.artifacts import ArtifactStore

ARTIFACT_KIND = "traces"


class TraceNotFoundError(KeyError):
    """No trace with the requested id."""


class TraceRepository:
    """Stores and reloads traces.

    The full trace lives as a JSONL artifact; the database indexes it so
    scenarios and outcomes are queryable without parsing every file.
    """

    def __init__(self, connection: sqlite3.Connection, artifacts: ArtifactStore) -> None:
        self._connection = connection
        self._artifacts = artifacts

    def save(self, trace: Trace) -> Path:
        """Persist a trace and index it. Returns the artifact path."""
        path = self._artifacts.write_text(
            ARTIFACT_KIND, f"{trace.trace_id}.jsonl", trace.to_jsonl()
        )
        injection = trace.injection
        self._connection.execute(
            """
            INSERT INTO traces (
                trace_id, scenario_id, agent_version, seed, outcome, oracle,
                injected, injection_kind, true_causal_step, step_count,
                content_hash, artifact_path, started_at, finished_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trace_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                artifact_path = excluded.artifact_path
            """,
            (
                trace.trace_id,
                trace.scenario_id,
                trace.agent_version,
                trace.seed,
                trace.outcome.status.value,
                trace.outcome.oracle,
                1 if injection else 0,
                injection.kind if injection else None,
                injection.true_causal_step if injection else None,
                len(trace.steps),
                trace.content_hash(),
                str(path),
                trace.started_at.isoformat(),
                trace.finished_at.isoformat(),
            ),
        )
        self._connection.commit()
        return path

    def load(self, trace_id: str) -> Trace:
        """Reload a trace from its artifact.

        Raises:
            TraceNotFoundError: if the id is unknown.
            ValueError: if the artifact's content no longer matches its recorded hash.
        """
        row = self._connection.execute(
            "SELECT artifact_path, content_hash FROM traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if row is None:
            raise TraceNotFoundError(f"no trace {trace_id!r}")

        trace = Trace.from_jsonl(self._artifacts.read_text(row["artifact_path"]))
        if trace.content_hash() != row["content_hash"]:
            raise ValueError(
                f"trace {trace_id!r} artifact does not match its indexed hash — "
                "the evidence on disk was altered"
            )
        return trace

    def list_by_scenario(self, scenario_id: str) -> list[str]:
        rows = self._connection.execute(
            "SELECT trace_id FROM traces WHERE scenario_id = ? ORDER BY created_at, trace_id",
            (scenario_id,),
        ).fetchall()
        return [row["trace_id"] for row in rows]

    def count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) AS n FROM traces").fetchone()["n"])
