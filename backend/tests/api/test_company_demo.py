"""The company demo, and the incident identity that must survive the transition.

The product claim this file defends: a viewer watches one execution fail in the
company app, clicks through, and investigates **that same execution** — not
another run that resembles it. If incident identity broke across the boundary,
the demo would be a slideshow with a convincing story over it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aftermath.api.app import create_app
from aftermath.api.company import DEMO_INCIDENT
from aftermath.config import REPO_ROOT, Settings
from aftermath.injection.incidents import load_incidents
from aftermath.injection.runner import run_incident

FRONTEND = REPO_ROOT / "frontend" / "index.html"


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    return TestClient(create_app(Settings(artifact_dir=tmp_path_factory.mktemp("a"))))


class TestCompanyDemoRuns:
    def test_demo_loads(self, client: TestClient) -> None:
        payload = client.get("/api/company/scenarios").json()

        assert payload["company"]
        assert payload["demo_incident"] == DEMO_INCIDENT
        assert payload["customer_message"]

    def test_healthy_run_executes_the_real_agent_and_passes(self, client: TestClient) -> None:
        payload = client.post("/api/company/run", json={"incident_id": None}).json()

        assert payload["outcome"]["status"] == "PASS"
        assert payload["activity"], "no agent activity produced"
        # Refunded exactly what the current policy entitles.
        assert payload["refunded_cents"] == payload["context"]["eligibility"]["entitled_cents"]
        assert payload["monitoring"]["captured"] is False
        assert "incident" not in payload

    def test_incident_run_fails_visibly(self, client: TestClient) -> None:
        payload = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()

        assert payload["outcome"]["status"] == "FAIL"
        incident = payload["incident"]
        # The failure must be obvious to a non-technical viewer: refunded far
        # more than entitled.
        assert incident["observed_cents"] > incident["expected_cents"]
        assert payload["monitoring"]["captured"] is True

    def test_unknown_incident_is_404(self, client: TestClient) -> None:
        assert client.post("/api/company/run", json={"incident_id": "I-999"}).status_code == 404

    def test_reruns_are_identical(self, client: TestClient) -> None:
        """Reset/re-run must reproduce, not drift."""
        a = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()
        b = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()

        assert a["activity"] == b["activity"]
        assert a["outcome"] == b["outcome"]


class TestActivityFeedIsTheRealTrace:
    """Nothing may appear in the feed that the agent did not do."""

    def test_every_feed_entry_maps_to_a_real_trace_step(self, client: TestClient) -> None:
        payload = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()
        trace = run_incident(load_incidents()[DEMO_INCIDENT]).run.trace
        real = {s.step_id for s in trace.steps}

        assert payload["activity"]
        for entry in payload["activity"]:
            assert entry["step_id"] in real, f"feed invents step {entry['step_id']}"

    def test_feed_tool_names_match_the_trace(self, client: TestClient) -> None:
        payload = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()
        trace = run_incident(load_incidents()[DEMO_INCIDENT]).run.trace
        by_id = {s.step_id: s for s in trace.steps}

        for entry in payload["activity"]:
            if entry["kind"] == "tool":
                assert by_id[entry["step_id"]].tool == entry["tool"]

    def test_context_comes_from_the_simulated_world(self, client: TestClient) -> None:
        from aftermath.companyagent.world import build_world

        payload = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()
        world = build_world()
        order = world.orders[payload["context"]["order"]["id"]]

        assert payload["context"]["order"]["amount_cents"] == order.amount_cents
        assert payload["context"]["policy"]["version"] == world.effective_policy("refund").version


class TestIncidentIdentitySurvivesTheTransition:
    """One incident, followed across the whole product."""

    def test_company_incident_id_is_a_real_benchmark_incident(self, client: TestClient) -> None:
        payload = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()

        assert payload["incident"]["incident_id"] in load_incidents()

    def test_the_same_id_opens_the_same_investigation(self, client: TestClient) -> None:
        run = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()
        incident_id = run["incident"]["incident_id"]

        investigation = client.get(f"/api/incidents/{incident_id}/investigation").json()

        assert investigation["incident_id"] == incident_id
        assert investigation["step_count"] == run["incident"]["captured_steps"]

    def test_the_same_id_opens_the_same_trace(self, client: TestClient) -> None:
        run = client.post("/api/company/run", json={"incident_id": DEMO_INCIDENT}).json()
        incident_id = run["incident"]["incident_id"]

        trace = client.get(f"/api/incidents/{incident_id}/trace").json()

        assert len(trace["steps"]) == run["incident"]["captured_steps"]
        assert trace["outcome"]["detail"] == run["outcome"]["detail"]

    def test_replay_and_immunity_refer_to_the_same_incident(self, client: TestClient) -> None:
        investigation = client.get(f"/api/incidents/{DEMO_INCIDENT}/investigation").json()
        vault = client.get("/api/immunity").json()

        assert investigation["immunity"]["acquired"] is True
        assert any(c["incident_id"] == DEMO_INCIDENT for c in vault["cases"])
        assert investigation["immunity"]["case_id"] in {c["case_id"] for c in vault["cases"]}


class TestInvestigationIsMeasuredNotNarrated:
    def test_cause_matches_injector_ground_truth(self, client: TestClient) -> None:
        d = client.get(f"/api/incidents/{DEMO_INCIDENT}/investigation").json()

        assert d["root_cause_step"] == d["true_causal_step"]

    def test_experiments_carry_real_measurements(self, client: TestClient) -> None:
        d = client.get(f"/api/incidents/{DEMO_INCIDENT}/investigation").json()

        assert d["experiments"]
        prevented = [e for e in d["experiments"] if e["prevented"]]
        assert prevented, "no experiment prevented the failure"
        for e in d["experiments"]:
            assert e["artifact_hash"].startswith("sha256:")
            assert e["baseline_failures"] <= e["trials"]

    def test_immunity_is_claimed_only_when_a_case_exists(self, client: TestClient) -> None:
        """'Immunity acquired' must never be decoration."""
        acquired = client.get(f"/api/incidents/{DEMO_INCIDENT}/investigation").json()
        # I-005 has no acceptable repair, so it must NOT claim immunity.
        none = client.get("/api/incidents/I-005/investigation").json()

        assert acquired["immunity"]["acquired"] is True
        assert none["immunity"]["acquired"] is False
        assert none["repair_accepted"] is False

    def test_unknown_incident_is_404(self, client: TestClient) -> None:
        assert client.get("/api/incidents/I-999/investigation").status_code == 404


class TestConsoleStructure:
    def test_company_demo_is_the_default_view(self) -> None:
        """The story before the score: a new visitor must not land on Benchmark."""
        source = FRONTEND.read_text(encoding="utf-8")

        assert re.search(r'show\("company"\);\s*$', source.strip().split("</script>")[0].strip()) \
            or 'show("company")' in source.split("get(\"/benchmark\")")[-1]

    def test_console_offers_the_company_and_forensic_views(self) -> None:
        source = FRONTEND.read_text(encoding="utf-8")

        for view in ("Company Demo", "Incident", "Evidence Board", "Replay Lab",
                     "Immunity Vault", "Benchmark"):
            assert f'"{view}"' in source, f"missing view: {view}"

    def test_transition_carries_the_incident(self) -> None:
        source = FRONTEND.read_text(encoding="utf-8")

        assert "openInAftermath" in source
        assert "ACTIVE = incidentId" in source
        # Forensic views must reload against the carried incident.
        assert 'get(`/incidents/${ACTIVE}/investigation`)' in source

    def test_console_still_hard_codes_no_result(self) -> None:
        """The P9 rule survives the new views."""
        source = FRONTEND.read_text(encoding="utf-8")

        for forbidden in ("0.95", "0.90", "0.75", "19/20", "18/20", "RELEASE OK"):
            assert forbidden not in source

    def test_console_invents_no_agent_steps(self) -> None:
        """Feed labels are presentational; the steps come from the backend."""
        source = FRONTEND.read_text(encoding="utf-8")

        assert "d.activity.forEach" in source
        for fabricated in ("Thinking…", "Analyzing…", "Neural", "AI brain"):
            assert fabricated not in source
