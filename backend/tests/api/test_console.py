"""The console API, and the rule that no displayed value may be invented.

`CLAUDE.md` §3–4: every number shown anywhere traces to a stored artifact, and
the UI reflects real backend state. The cheapest way to guarantee that is for
the API to serve only what exists and for the frontend to contain no data of its
own — both are asserted here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aftermath.api.app import create_app
from aftermath.config import REPO_ROOT, Settings
from aftermath.injection.incidents import load_incidents

RESULTS = REPO_ROOT / "data" / "results"
FRONTEND = REPO_ROOT / "frontend" / "index.html"


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    return TestClient(create_app(Settings(artifact_dir=tmp_path_factory.mktemp("a"))))


class TestArtifactsAreServedNotInvented:
    def test_benchmark_matches_the_file_on_disk(self, client: TestClient) -> None:
        served = client.get("/api/benchmark").json()
        stored = json.loads((RESULTS / "benchmark.json").read_text(encoding="utf-8"))

        assert served["artifact_hash"] == stored["artifact_hash"]
        assert served["aftermath_localization_rate"] == stored["aftermath_localization_rate"]

    def test_sweep_matches_the_file_on_disk(self, client: TestClient) -> None:
        served = client.get("/api/sweep").json()
        stored = json.loads(
            (RESULTS / "investigator_recall_sweep.json").read_text(encoding="utf-8")
        )

        assert served["artifact_hash"] == stored["artifact_hash"]

    def test_missing_artifact_is_404_not_an_empty_shape(self, client: TestClient) -> None:
        """A missing result must not render as a plausible-looking zero."""
        from aftermath.api import routes

        original = routes.RESULTS_DIR
        routes.RESULTS_DIR = Path("/nonexistent")
        try:
            response = client.get("/api/benchmark")
        finally:
            routes.RESULTS_DIR = original

        assert response.status_code == 404
        assert "has not been produced" in response.json()["detail"]

    def test_history_shows_the_superseded_run(self, client: TestClient) -> None:
        """A changed result must be visible as a change, not silently replaced."""
        runs = client.get("/api/benchmark/history").json()["runs"]

        rates = [r["aftermath"] for r in runs]
        assert 0.75 in rates and 0.90 in rates


class TestIncidentAndTraceEndpoints:
    def test_incident_list_matches_the_definitions(self, client: TestClient) -> None:
        payload = client.get("/api/incidents").json()

        assert payload["count"] == len(load_incidents())
        for row in payload["incidents"]:
            assert row["true_causal_step"], "ground truth must be resolved by running"

    def test_trace_is_the_real_recorded_trace(self, client: TestClient) -> None:
        from aftermath.injection.runner import run_incident

        served = client.get("/api/incidents/I-001/trace").json()
        actual = run_incident(load_incidents()["I-001"]).run.trace

        assert served["content_hash"] == actual.content_hash()
        assert len(served["steps"]) == len(actual.steps)
        assert served["injection"]["true_causal_step"] == actual.injection.true_causal_step

    def test_unknown_incident_is_404(self, client: TestClient) -> None:
        assert client.get("/api/incidents/I-999/trace").status_code == 404


class TestImmunityGateIsExecutedNotStored:
    def test_gate_runs_against_the_current_code(self, client: TestClient) -> None:
        """A stale stored verdict would be exactly the decorative number this forbids."""
        payload = client.get("/api/immunity").json()

        assert payload["gate"]["unrepaired"]["protected"] == 0
        assert payload["gate"]["repaired"]["verdict"] == "RELEASE OK"
        assert payload["cases"]

    def test_dropping_a_guardrail_really_runs_the_suite(self, client: TestClient) -> None:
        payload = client.get("/api/immunity/drop/idempotent_refund").json()

        assert payload["verdict"] == "RELEASE WARNING"
        assert payload["regressions"], "dropping a load-bearing guard must regress cases"
        assert all(r["detail"] for r in payload["regressions"])

    def test_unknown_guardrail_is_404(self, client: TestClient) -> None:
        assert client.get("/api/immunity/drop/not_a_guard").status_code == 404


class TestFrontendHasNoDataOfItsOwn:
    """The UI must be a view, never a source."""

    def test_console_is_served_by_our_own_backend(self, client: TestClient) -> None:
        """The browser talks only to us, so no provider key can reach it."""
        response = client.get("/")

        assert response.status_code == 200
        assert "AFTERMATH" in response.text

    def test_frontend_contains_no_hard_coded_results(self) -> None:
        """A number baked into the UI would survive the artifact being deleted."""
        source = FRONTEND.read_text(encoding="utf-8")

        for forbidden in ("0.95", "0.90", "0.75", "19/20", "18/20", "RELEASE OK"):
            assert forbidden not in source, f"UI hard-codes a result: {forbidden}"

    def test_frontend_declares_no_fallback_data(self) -> None:
        """No mock/sample/demo payload that could stand in for a real one."""
        source = FRONTEND.read_text(encoding="utf-8").lower()

        for forbidden in ("mockdata", "sampledata", "fakedata", "demodata", "placeholder"):
            assert forbidden not in source

    def test_frontend_reaches_only_our_api(self) -> None:
        """No external host, so nothing renders from a source we do not control."""
        source = FRONTEND.read_text(encoding="utf-8")

        assert not re.search(r"""(?:src|href)\s*=\s*["']https?://""", source)
        assert 'const API = "/api"' in source

    def test_every_fetch_targets_a_real_endpoint(self, client: TestClient) -> None:
        """A view pointing at a nonexistent route would render empty forever."""
        source = FRONTEND.read_text(encoding="utf-8")
        # Static paths the console requests, e.g. get("/benchmark"). A trailing
        # slash marks a prefix that is concatenated with an id at call time;
        # those are covered by test_dynamic_endpoints_resolve_for_real_ids.
        paths = {
            p
            for p in re.findall(r"""get\(\s*["'](/[A-Za-z0-9_/-]+)""", source)
            if not p.endswith("/")
        }

        assert paths, "no API calls found in the console"
        for path in paths:
            assert client.get(f"/api{path}").status_code == 200, (
                f"console calls /api{path}, which the API does not serve"
            )

    def test_dynamic_endpoints_resolve_for_real_ids(self, client: TestClient) -> None:
        """Paths built by string concatenation are checked with a real value."""
        source = FRONTEND.read_text(encoding="utf-8")

        assert "/incidents/${id}/trace" in source
        assert "/immunity/drop/" in source
        assert client.get("/api/incidents/I-001/trace").status_code == 200
        assert client.get("/api/immunity/drop/idempotent_refund").status_code == 200
