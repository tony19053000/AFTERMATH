"""Metric computation over graded answers.

Every number the project reports is computed here, from stored artifacts, by
deterministic Python. No metric is ever produced by a model, estimated, or
written by hand (`docs/PROJECT_REQUIREMENTS.md` §10).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aftermath.benchmark.grader import GradedAnswer, Verdict
from aftermath.core.hashing import content_hash


class SystemMetrics(BaseModel):
    """One system's performance over the incident set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str
    incidents: int = Field(gt=0)
    exact: int = Field(ge=0)
    near_miss: int = Field(ge=0)
    wrong: int = Field(ge=0)
    no_answer: int = Field(ge=0)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0

    @property
    def localization_rate(self) -> float:
        """THE primary metric. Exact matches only — a near miss is not a success."""
        return self.exact / self.incidents

    @property
    def near_miss_rate(self) -> float:
        return self.near_miss / self.incidents

    @property
    def answered_rate(self) -> float:
        return (self.incidents - self.no_answer) / self.incidents

    @property
    def in_causal_set_rate(self) -> float:
        """Named *some* genuinely causal step. Reported as context, never as the headline."""
        return (self.exact + self.near_miss) / self.incidents

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def summarize(
    system: str,
    answers: list[GradedAnswer],
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_seconds: float = 0.0,
) -> SystemMetrics:
    """Count verdicts into metrics.

    Raises:
        ValueError: if there are no answers — an empty run has no rate, and
            returning 0.0 would read as a measured failure rather than no data.
    """
    if not answers:
        raise ValueError(f"no graded answers for {system!r}: nothing to summarize")
    counts = {v: 0 for v in Verdict}
    for answer in answers:
        counts[answer.verdict] += 1
    return SystemMetrics(
        system=system,
        incidents=len(answers),
        exact=counts[Verdict.EXACT],
        near_miss=counts[Verdict.NEAR_MISS],
        wrong=counts[Verdict.WRONG],
        no_answer=counts[Verdict.NO_ANSWER],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_seconds=latency_seconds,
    )


class Comparison(BaseModel):
    """AFTERMATH against the baseline, on an identical incident set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aftermath: SystemMetrics
    baseline: SystemMetrics
    incident_ids: tuple[str, ...]

    @property
    def delta(self) -> float:
        """Primary-metric difference. Negative means the baseline won."""
        return self.aftermath.localization_rate - self.baseline.localization_rate

    @property
    def verdict(self) -> str:
        if self.delta > 0:
            return "AFTERMATH ahead"
        if self.delta < 0:
            return "BASELINE ahead"
        return "TIED"

    def to_artifact(self) -> dict:
        """Serializable record of the run.

        ``artifact_hash`` covers only the *reproducible* content. Wall-clock
        latency is reported but excluded from the hash: it varies between runs of
        an otherwise identical benchmark, and including it would mean no two
        artifacts of the same result ever matched — making the hash useless for
        the one job it has.
        """
        payload = {
            "incident_ids": list(self.incident_ids),
            "aftermath": self.aftermath.model_dump(mode="json"),
            "baseline": self.baseline.model_dump(mode="json"),
            "aftermath_localization_rate": self.aftermath.localization_rate,
            "baseline_localization_rate": self.baseline.localization_rate,
            "aftermath_in_causal_set_rate": self.aftermath.in_causal_set_rate,
            "baseline_in_causal_set_rate": self.baseline.in_causal_set_rate,
            "delta": self.delta,
            "verdict": self.verdict,
        }
        payload["artifact_hash"] = content_hash(
            {
                k: (
                    {ik: iv for ik, iv in v.items() if ik != "latency_seconds"}
                    if isinstance(v, dict)
                    else v
                )
                for k, v in payload.items()
            }
        )
        return payload
