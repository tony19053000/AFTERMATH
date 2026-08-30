"""Persistent storage for regression cases.

Cases are JSON under `data/immunity/`, committed to the repository. Unlike
experiment artifacts — which are regenerable — a case is a durable record that a
particular failure was diagnosed, repaired, and must never return. It belongs in
version control so a release gate is reviewable in a diff.

A case is only admitted after its controls pass, so the vault cannot accumulate
cases that silently detect nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from aftermath.config import REPO_ROOT
from aftermath.immunity.case import RegressionCase
from aftermath.immunity.runner import verify_case_controls
from aftermath.replay.repair import RepairSpec

VAULT_DIR = REPO_ROOT / "data" / "immunity"


class ImmunityVault:
    """Reads and writes regression cases."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else VAULT_DIR

    def store(self, case: RegressionCase, *, verify: bool = True) -> Path:
        """Admit a case to the vault.

        Raises:
            CaseControlsFailed: if the case does not fail unrepaired and pass
                repaired. Verification can be skipped only for tests that are
                deliberately constructing a broken case.
        """
        if verify:
            verify_case_controls(case)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{case.case_id}.json"
        path.write_text(
            json.dumps(case.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def load_all(self) -> list[RegressionCase]:
        """Every stored case, ordered by id for stable suite output."""
        if not self.directory.exists():
            return []
        return [
            RegressionCase.model_validate(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(self.directory.glob("*.json"))
        ]

    def load(self, case_id: str) -> RegressionCase:
        """Load one case.

        Raises:
            KeyError: if no such case is stored.
        """
        path = self.directory / f"{case_id}.json"
        if not path.exists():
            raise KeyError(f"no regression case {case_id!r} in {self.directory}")
        return RegressionCase.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def repairs_of_record(self) -> tuple[RepairSpec, ...]:
        """Every verified repair across the vault — the guardrails a release ships."""
        seen: dict[str, RepairSpec] = {}
        for case in self.load_all():
            seen.setdefault(case.verified_repair.kind.value, case.verified_repair)
        return tuple(seen.values())
