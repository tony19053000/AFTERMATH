"""Incident definitions: the benchmark's ground-truth records.

An incident pairs a scenario with a fault, and states in advance what should have
happened and what actually did. Definitions live as JSON under `data/incidents/`
so they are inspectable, diffable, and reviewable independently of the code.

`true_causal_step` is **not** stored in the definition file. It is produced by the
injector at run time, because step ids are ordinal and only exist once a run has
happened. Writing it by hand would mean asserting a causal claim without having
run anything — exactly the habit this project exists to replace.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aftermath.config import REPO_ROOT
from aftermath.core.trace import Severity
from aftermath.injection.spec import InjectionSpec

INCIDENT_DIR = REPO_ROOT / "data" / "incidents"


class ReplayConfiguration(BaseModel):
    """How P4 should replay this incident when measuring effect sizes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int = 1337
    trials: int = 20
    mode: str = "strict"


class IncidentDefinition(BaseModel):
    """One benchmark incident with controlled, known provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)

    expected_behavior: str = Field(min_length=1)
    observed_behavior: str = Field(min_length=1)
    expected_safe_behavior: str = Field(min_length=1)

    injected_failure: InjectionSpec
    # The oracle that must FAIL when the fault is applied. Named explicitly so a
    # broken incident (one that fails for an unrelated reason) is detectable.
    failing_oracle: str = Field(min_length=1)
    severity: Severity = Severity.HIGH
    replay_configuration: ReplayConfiguration = ReplayConfiguration()

    @property
    def ground_truth_source(self) -> str:
        """Provenance of this incident's ground truth. Always the injector (D-002)."""
        return "fault_injector"


def load_incident(path: Path) -> IncidentDefinition:
    """Load and validate one incident definition.

    Raises:
        ValueError: if the file is not valid JSON or fails schema validation.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    return IncidentDefinition.model_validate(payload)


def load_incidents(directory: Path | None = None) -> dict[str, IncidentDefinition]:
    """Load every incident definition, keyed by id.

    Raises:
        ValueError: on a duplicate incident id, which would silently shrink the
            benchmark and skew every rate computed over it.
    """
    root = directory or INCIDENT_DIR
    incidents: dict[str, IncidentDefinition] = {}
    for path in sorted(root.glob("*.json")):
        incident = load_incident(path)
        if incident.incident_id in incidents:
            raise ValueError(f"duplicate incident_id {incident.incident_id!r} in {path.name}")
        incidents[incident.incident_id] = incident
    return incidents
