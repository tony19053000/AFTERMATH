"""FastAPI application skeleton.

Only `/health` exists in P1. Pipeline routes arrive with the phases that
implement them, so the API never advertises a capability that isn't real.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aftermath.api.company import router as company_router
from aftermath.api.routes import router
from aftermath.config import REPO_ROOT, Settings, get_settings

API_VERSION = "0.1.0"
FRONTEND = REPO_ROOT / "frontend" / "index.html"


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
    app.include_router(router, prefix="/api")
    app.include_router(company_router, prefix="/api")

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": API_VERSION,
            "llm_provider": resolved.llm_provider.value,
            "deterministic_provider": resolved.llm_provider.value == "mock",
        }

    @app.get("/", include_in_schema=False)
    def console() -> FileResponse:
        """Serve the console from our own backend.

        The browser therefore talks only to us, and never holds a provider key —
        a standing security rule, and the reason the UI is served rather than
        opened from the filesystem against a cross-origin API.
        """
        return FileResponse(FRONTEND)

    return app


app = create_app()
