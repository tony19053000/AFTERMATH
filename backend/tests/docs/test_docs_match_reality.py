"""Documentation claims, checked against the repository.

`CLAUDE.md` §1 says a document contradicting the code is a bug in the document.
Until now nothing enforced that, and STATUS.md drifted on seven counts at once —
it described a 758-line package as an empty stub, claimed committed cassettes
were gitignored, cited a commit hash that was never HEAD, and carried a
superseded headline that contradicted a table two sections below it.

Test counts and benchmark numbers were already verified. These checks extend
that to the prose claims that were not, so the same class of drift fails loudly
instead of accumulating.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from aftermath.config import REPO_ROOT

STATUS = REPO_ROOT / "docs" / "STATUS.md"
README = REPO_ROOT / "README.md"
RESULTS = REPO_ROOT / "data" / "results"


@pytest.fixture(scope="module")
def status() -> str:
    return STATUS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def benchmark() -> dict:
    return json.loads((RESULTS / "benchmark.json").read_text(encoding="utf-8"))


class TestStatusMatchesTheRepository:
    def test_recorded_commit_is_a_real_ancestor_of_head(self, status: str) -> None:
        """The hash must name a commit that is genuinely in this branch's history.

        Being a commit or two behind HEAD is normal and not drift: a feature
        commit is recorded, then a docs commit follows it. What would be drift is
        a hash that names nothing, or one from an abandoned branch.
        """
        match = re.search(r"\*\*Last verified commit:\*\* `([0-9a-f]{7,})`", status)
        assert match, "STATUS records no verified commit"
        recorded = match.group(1)

        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{recorded}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        assert exists.returncode == 0, f"commit {recorded} is not in this repository"

        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", recorded, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        assert ancestry.returncode == 0, f"commit {recorded} is not an ancestor of HEAD"

    def test_no_package_called_a_stub_actually_has_code(self, status: str) -> None:
        """STATUS described `benchmark/` as an empty stub while it held 758 lines."""
        claimed = re.findall(r"`([a-z_]+)/`[^.\n]*(?:empty package stub|stub)", status)

        for package in claimed:
            directory = REPO_ROOT / "backend" / "aftermath" / package
            if not directory.exists():
                continue
            lines = sum(
                len(p.read_text(encoding="utf-8").splitlines())
                for p in directory.glob("*.py")
                if p.name != "__init__.py"
            )
            assert lines == 0, f"{package}/ is called a stub but has {lines} lines"

    def test_incident_count_claim_matches_the_directory(self, status: str) -> None:
        actual = len(list((REPO_ROOT / "data" / "incidents").glob("*.json")))

        assert f"{actual} incidents" in status, f"STATUS does not state the real count ({actual})"

    def test_immunity_case_count_claim_matches_the_vault(self, status: str) -> None:
        actual = len(list((REPO_ROOT / "data" / "immunity").glob("*.json")))

        assert f"{actual} cases" in status

    def test_claims_about_cassettes_match_whether_they_are_tracked(self, status: str) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "data/cassettes/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout.split()

        if tracked:
            assert "cassettes are gitignored" not in status.lower()
            assert "not reproducible from a clean clone" not in status.lower()

    def test_test_count_claim_is_current(self, status: str) -> None:
        match = re.search(r"\*\*(\d+) passed\*\*", status)
        assert match, "STATUS states no test count"

        result = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "backend/tests", "-q", "--collect-only"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        collected = re.search(r"(\d+)/(\d+) tests collected", result.stdout) or re.search(
            r"(\d+) tests collected", result.stdout
        )
        if not collected:
            pytest.skip("could not determine collected test count")

        claimed = int(match.group(1))
        actual = int(collected.group(1))
        # Deselected `live` tests mean claimed <= collected; a claim ABOVE the
        # collected total is always wrong.
        assert claimed <= actual, f"STATUS claims {claimed} passing, only {actual} exist"


class TestPublishedNumbersComeFromArtifacts:
    def test_status_benchmark_table_matches_the_artifact(
        self, status: str, benchmark: dict
    ) -> None:
        aftermath = f"{benchmark['aftermath_localization_rate']:.2f}"
        baseline = f"{benchmark['baseline_localization_rate']:.2f}"

        assert aftermath in status and baseline in status
        assert benchmark["verdict"] in status

    def test_readme_benchmark_numbers_match_the_artifact(self, benchmark: dict) -> None:
        readme = README.read_text(encoding="utf-8")

        assert f"{benchmark['aftermath_localization_rate']:.2f}" in readme
        assert f"{benchmark['baseline_localization_rate']:.2f}" in readme

    def test_sweep_numbers_in_status_match_the_artifact(self, status: str) -> None:
        sweep = json.loads(
            (RESULTS / "investigator_recall_sweep.json").read_text(encoding="utf-8")
        )

        for arm in sweep["arms"]:
            assert f"{arm['recall']:.2f}" in status
            assert f"{arm['tokens_per_incident']:,.0f}" in status


class TestNoUnearnedClaims:
    """Standing prohibitions from `CLAUDE.md` §10 and D-009."""

    @pytest.mark.parametrize("doc", ["README.md", "docs/STATUS.md", "docs/ARCHITECTURE.md"])
    def test_no_tee_or_attestation_claim(self, doc: str) -> None:
        text = (REPO_ROOT / doc).read_text(encoding="utf-8").lower()

        for phrase in ("runs in a tee", "attested execution", "remote attestation verified"):
            assert phrase not in text
        # Mentioning TEE as future work is fine; claiming it runs is not.
        if "tee" in text:
            assert "not implemented" in text or "future" in text or "optional" in text

    def test_status_does_not_contradict_its_own_benchmark_table(
        self, status: str, benchmark: dict
    ) -> None:
        """The drift that mattered most: a stale headline above a correct table."""
        if benchmark["verdict"] == "TIED":
            assert "THE BASELINE WON" not in status.upper()
