"""FastAPI application skeleton.

Only `/health` exists in P1. Pipeline routes arrive with the phases that
implement them, so the API never advertises a capability that isn't real.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from aftermath.config import Settings, get_settings

API_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_provider: str
    # Reported so a caller can tell whether results came from a deterministic
    # offline provider or a live model.
    deterministic_provider: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(
        title="AFTERMATH",
        version=API_VERSION,
        description="From Agent Incident to Verified Immunity.",
    )
    app.state.settings = resolved

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": API_VERSION,
            "llm_provider": resolved.llm_provider.value,
            "deterministic_provider": resolved.llm_provider.value == "mock",
        }

    return app


app = create_app()
