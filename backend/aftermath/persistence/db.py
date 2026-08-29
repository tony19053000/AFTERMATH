"""SQLite schema and connection handling.

Accessed only through the repository layer, which is the seam for a future
PostgreSQL migration (`docs/DECISIONS.md` D-005). Large payloads live in the
artifact store; the database holds indexes, relationships, and hashes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

# Tables beyond `traces` are created now so that later phases add rows, not
# migrations. Payload columns hold artifact paths, not blobs.
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    trace_id      TEXT PRIMARY KEY,
    scenario_id   TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    seed          INTEGER NOT NULL,
    outcome       TEXT NOT NULL,
    oracle        TEXT NOT NULL,
    injected      INTEGER NOT NULL DEFAULT 0,
    injection_kind TEXT,
    true_causal_step TEXT,
    step_count    INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_traces_scenario ON traces(scenario_id);
CREATE INDEX IF NOT EXISTS idx_traces_hash     ON traces(content_hash);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id   TEXT PRIMARY KEY,
    scenario_id   TEXT NOT NULL,
    description   TEXT NOT NULL,
    severity      TEXT NOT NULL,
    definition_path TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id     TEXT PRIMARY KEY,
    trace_id          TEXT NOT NULL REFERENCES traces(trace_id),
    suspected_step_id TEXT NOT NULL,
    mechanism         TEXT NOT NULL,
    confidence        REAL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id   TEXT PRIMARY KEY,
    hypothesis_id   TEXT REFERENCES hypotheses(hypothesis_id),
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    intervention    TEXT NOT NULL,
    trials          INTEGER NOT NULL,
    baseline_failures INTEGER,
    intervened_failures INTEGER,
    effect_size     REAL,
    artifact_path   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS repairs (
    repair_id     TEXT PRIMARY KEY,
    incident_id   TEXT REFERENCES incidents(incident_id),
    strategy      TEXT NOT NULL,
    description   TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS repair_evaluations (
    evaluation_id    TEXT PRIMARY KEY,
    repair_id        TEXT NOT NULL REFERENCES repairs(repair_id),
    prevention_rate  REAL,
    false_block_rate REAL,
    artifact_path    TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS regression_cases (
    case_id       TEXT PRIMARY KEY,
    incident_id   TEXT REFERENCES incidents(incident_id),
    scenario_id   TEXT NOT NULL,
    seed          INTEGER NOT NULL,
    definition_path TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    run_id        TEXT PRIMARY KEY,
    system        TEXT NOT NULL,
    incident_count INTEGER NOT NULL,
    artifact_path TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id       TEXT PRIMARY KEY,
    trace_id      TEXT,
    model         TEXT NOT NULL,
    tag           TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    from_record   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Create the schema if absent and stamp its version."""
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()


@contextmanager
def session(path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open an initialized connection, committing on success and closing always."""
    connection = connect(path)
    try:
        initialize(connection)
        yield connection
        connection.commit()
    finally:
        connection.close()
