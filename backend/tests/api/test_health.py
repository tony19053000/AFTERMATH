"""API skeleton. P1 acceptance: /health returns 200."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aftermath.api.app import API_VERSION, create_app
from aftermath.config import LLMProviderName, Settings


def test_health_returns_ok(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(artifact_dir=tmp_path)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": API_VERSION,
        "llm_provider": "mock",
        "deterministic_provider": True,
    }


def test_health_reports_non_deterministic_provider_honestly(tmp_path: Path) -> None:
    """A caller must be able to tell whether results came from a live model."""
    settings = Settings(artifact_dir=tmp_path, llm_provider=LLMProviderName.GEMINI)
    client = TestClient(create_app(settings))

    body = client.get("/health").json()

    assert body["llm_provider"] == "gemini"
    assert body["deterministic_provider"] is False


def test_unimplemented_routes_are_absent(tmp_path: Path) -> None:
    """The API must not advertise a capability that does not exist yet."""
    client = TestClient(create_app(Settings(artifact_dir=tmp_path)))

    for route in ("/incidents/x/investigate", "/experiments", "/benchmark/run"):
        assert client.get(route).status_code == 404
