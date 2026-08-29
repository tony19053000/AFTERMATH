"""Persistence: schema creation, trace save/reload, artifact integrity.

P1 acceptance: the SQLite schema creates, and a trace persists and reloads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aftermath.config import Settings
from aftermath.core.trace import Trace
from aftermath.persistence.artifacts import ArtifactStore
from aftermath.persistence.db import SCHEMA_VERSION, connect, initialize, session
from aftermath.persistence.trace_repository import TraceNotFoundError, TraceRepository
from tests.conftest import build_trace


@pytest.fixture
def repository(tmp_path: Path):
    connection = connect(tmp_path / "test.db")
    initialize(connection)
    store = ArtifactStore(tmp_path / "artifacts")
    yield TraceRepository(connection, store), store
    connection.close()


class TestSchema:
    def test_schema_creates_and_stamps_version(self, tmp_path: Path) -> None:
        with session(tmp_path / "db.sqlite") as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            assert row["value"] == str(SCHEMA_VERSION)

    def test_initialize_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "db.sqlite"
        with session(path):
            pass
        with session(path) as connection:  # must not raise
            assert connection.execute("SELECT COUNT(*) AS n FROM traces").fetchone()["n"] == 0

    def test_expected_tables_exist(self, tmp_path: Path) -> None:
        with session(tmp_path / "db.sqlite") as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row["name"] for row in rows}

        assert {
            "traces",
            "incidents",
            "hypotheses",
            "experiments",
            "repairs",
            "repair_evaluations",
            "regression_cases",
            "benchmark_runs",
            "llm_calls",
        } <= tables


class TestTracePersistence:
    def test_save_then_load_returns_identical_trace(self, repository, sample_trace) -> None:
        repo, _ = repository
        repo.save(sample_trace)

        loaded = repo.load(sample_trace.trace_id)

        assert loaded == sample_trace
        assert loaded.content_hash() == sample_trace.content_hash()

    def test_save_indexes_ground_truth(self, repository, sample_trace) -> None:
        repo, _ = repository
        repo.save(sample_trace)

        row = repo._connection.execute(
            "SELECT injected, injection_kind, true_causal_step, step_count FROM traces "
            "WHERE trace_id = ?",
            (sample_trace.trace_id,),
        ).fetchone()

        assert row["injected"] == 1
        assert row["injection_kind"] == "stale_policy"
        assert row["true_causal_step"] == "s0003"
        assert row["step_count"] == len(sample_trace.steps)

    def test_unknown_trace_raises(self, repository) -> None:
        repo, _ = repository
        with pytest.raises(TraceNotFoundError):
            repo.load("does-not-exist")

    def test_list_by_scenario(self, repository) -> None:
        repo, _ = repository
        repo.save(build_trace("t-1"))
        repo.save(build_trace("t-2"))

        assert set(repo.list_by_scenario("refund_stale_policy_v1")) == {"t-1", "t-2"}
        assert repo.list_by_scenario("nonexistent") == []

    def test_resaving_same_trace_is_idempotent(self, repository, sample_trace) -> None:
        repo, _ = repository
        repo.save(sample_trace)
        repo.save(sample_trace)

        assert repo.count() == 1

    def test_tampered_artifact_is_detected(self, repository, sample_trace) -> None:
        """Evidence altered on disk must not load silently."""
        repo, _ = repository
        path = repo.save(sample_trace)

        content = Path(path).read_text(encoding="utf-8")
        Path(path).write_text(content.replace("Refund approved.", "Refund denied."), "utf-8")

        with pytest.raises(ValueError, match="content hash mismatch"):
            repo.load(sample_trace.trace_id)


class TestArtifactStore:
    def test_write_and_read(self, artifact_store: ArtifactStore) -> None:
        path = artifact_store.write_text("traces", "a.jsonl", "hello")

        assert artifact_store.read_text(path) == "hello"

    def test_rewriting_identical_content_is_allowed(self, artifact_store: ArtifactStore) -> None:
        artifact_store.write_text("traces", "a.jsonl", "hello")

        assert artifact_store.write_text("traces", "a.jsonl", "hello").exists()

    def test_overwriting_different_content_is_refused(
        self, artifact_store: ArtifactStore
    ) -> None:
        """Artifacts are immutable evidence."""
        artifact_store.write_text("traces", "a.jsonl", "hello")

        with pytest.raises(FileExistsError, match="immutable evidence"):
            artifact_store.write_text("traces", "a.jsonl", "different")

    def test_hash_verifies_integrity(self, artifact_store: ArtifactStore) -> None:
        path = artifact_store.write_text("traces", "a.jsonl", "hello")
        digest = artifact_store.hash_of(path)

        assert artifact_store.verify(path, digest)

        path.write_text("tampered", encoding="utf-8")
        assert not artifact_store.verify(path, digest)


class TestSettings:
    def test_sqlite_path_extracted(self, tmp_path: Path) -> None:
        settings = Settings(db_url=f"sqlite:///{tmp_path / 'x.db'}", artifact_dir=tmp_path)

        assert settings.sqlite_path() == tmp_path / "x.db"

    def test_non_sqlite_url_rejected(self, tmp_path: Path) -> None:
        settings = Settings(db_url="postgresql://localhost/x", artifact_dir=tmp_path)

        with pytest.raises(ValueError, match="not a SQLite URL"):
            settings.sqlite_path()
