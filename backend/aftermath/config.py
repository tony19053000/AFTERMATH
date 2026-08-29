"""Environment-driven configuration.

No secret is ever hard-coded here. Values come from the environment or a local
`.env` file (gitignored); `.env.example` documents the names with placeholders.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class LLMProviderName(StrEnum):
    """Selectable model providers. `MOCK` is deterministic and offline."""

    MOCK = "mock"
    GEMINI = "gemini"


class Settings(BaseSettings):
    """Application settings, read from the environment with an `AFTERMATH_` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="AFTERMATH_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: LLMProviderName = LLMProviderName.MOCK
    baseline_model: str = "gemini-2.5-pro"

    seed: int = 1337
    record_llm_calls: bool = True

    db_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'aftermath.db'}"
    artifact_dir: Path = REPO_ROOT / "data" / "artifacts"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"

    @field_validator("artifact_dir")
    @classmethod
    def _resolve_artifact_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    def sqlite_path(self) -> Path:
        """Filesystem path behind ``db_url``.

        Raises:
            ValueError: if ``db_url`` is not a SQLite URL. PostgreSQL support is a
                future phase; callers that need a path must not silently accept
                a non-SQLite backend.
        """
        prefix = "sqlite:///"
        if not self.db_url.startswith(prefix):
            raise ValueError(f"db_url is not a SQLite URL: {self.db_url!r}")
        return Path(self.db_url[len(prefix) :])


def get_settings(**overrides: object) -> Settings:
    """Build settings, optionally overridden (used by tests to avoid touching real paths)."""
    return Settings(**overrides)  # type: ignore[arg-type]
