"""The Immunity Vault: verified incidents as permanent regression tests.

P6 acceptance:
* a generated case FAILS against the unrepaired agent and PASSES against the
  repaired one — both asserted in Python,
* the suite runs against an arbitrary agent version and reports per-case status,
* a deliberately reintroduced bug is caught.

The two-direction control is the point. A case that passes against the
unrepaired agent detects nothing, and a suite full of those is a green light
that means nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aftermath.forensics.orchestrator import ForensicOrchestrator
from aftermath.immunity.case import CaseControlsFailed, RegressionCase, build_case
from aftermath.immunity.runner import (
    AgentVersion,
    ImmunityReport,
    run_case,
    run_suite,
    verify_case_controls,
)
from aftermath.immunity.vault import ImmunityVault
from aftermath.injection.incidents import load_incidents
from aftermath.replay.repair import RepairKind, RepairSpec

INCIDENTS = load_incidents()
TRIALS = 3
# I-005 has no acceptable repair, so it cannot become a case. That is correct
# behaviour, asserted below rather than worked around.
REPAIRABLE = ["I-001", "I-002", "I-003", "I-004"]


@pytest.fixture(scope="module")
def generated_cases() -> dict[str, RegressionCase]:
    """Cases built from real pipeline output, not hand-written."""
    orchestrator = ForensicOrchestrator(None, trials=TRIALS)
    cases: dict[str, RegressionCase] = {}
    for incident_id in REPAIRABLE:
        incident = INCIDENTS[incident_id]
        report = orchestrator.investigate(incident)
        evidence = next(
            a
            for a in report.experiments
            if a["intervention"]["step_id"] == report.root_cause_step
        )
        cases[incident_id] = build_case(
            incident,
            root_cause_step=report.root_cause_step,
            verified_repair=RepairSpec(
                kind=RepairKind(report.repair["kind"]), rationale=report.repair["rationale"]
            ),
            evidence_effect_size=evidence["effect_size"],
            evidence_artifact_hash=evidence["artifact_hash"],
        )
    return cases


class TestCaseControls:
    """Both directions, for every case. This is the load-bearing test of P6."""

    @pytest.mark.parametrize("incident_id", REPAIRABLE)
    def test_case_fails_against_the_unrepaired_agent(
        self, generated_cases, incident_id
    ) -> None:
        result = run_case(generated_cases[incident_id], AgentVersion.unrepaired())

        assert result.regressed, "a case that passes unrepaired detects nothing"

    @pytest.mark.parametrize("incident_id", REPAIRABLE)
    def test_case_passes_against_the_repaired_agent(
        self, generated_cases, incident_id
    ) -> None:
        case = generated_cases[incident_id]

        result = run_case(case, AgentVersion("repaired", (case.verified_repair,)))

        assert result.protected, result.detail

    @pytest.mark.parametrize("incident_id", REPAIRABLE)
    def test_controls_pass_as_a_unit(self, generated_cases, incident_id) -> None:
        verify_case_controls(generated_cases[incident_id])

    def test_a_case_with_no_repair_is_rejected(self, generated_cases) -> None:
        """A case whose 'repair' does not work must not be admitted."""
        broken = generated_cases["I-001"].model_copy(
            update={"verified_repair": RepairSpec(kind=RepairKind.IDEMPOTENT_REFUND)}
        )

        with pytest.raises(CaseControlsFailed, match="does not prevent"):
            verify_case_controls(broken)

    def test_a_case_that_cannot_fail_is_rejected(self, generated_cases) -> None:
        """Point a case at a scenario with no fault: it passes unrepaired, so it is useless."""
        toothless = generated_cases["I-001"].model_copy(
            update={"scenario_id": "cancel_pending_order"}
        )

        with pytest.raises(CaseControlsFailed, match="cannot detect the bug"):
            verify_case_controls(toothless)


class TestSuiteAndReleaseGate:
    def test_unrepaired_version_regresses_everything(self, generated_cases) -> None:
        report = run_suite(list(generated_cases.values()), AgentVersion.unrepaired())

        assert len(report.regressions) == len(generated_cases)
        assert report.protected == []
        assert report.release_blocked
        assert report.verdict == "RELEASE WARNING"

    def test_fully_repaired_version_is_protected(self, generated_cases) -> None:
        repairs = tuple({c.verified_repair.kind: c.verified_repair for c in
                         generated_cases.values()}.values())

        report = run_suite(list(generated_cases.values()), AgentVersion("v2.0", repairs))

        assert report.regressions == []
        assert not report.release_blocked
        assert report.verdict == "RELEASE OK"

    def test_reintroduced_bug_is_caught(self, generated_cases) -> None:
        """The scenario the vault exists for: a release quietly drops a guardrail."""
        cases = list(generated_cases.values())
        all_repairs = {c.verified_repair.kind: c.verified_repair for c in cases}
        dropped = RepairKind.IDEMPOTENT_REFUND
        partial = tuple(v for k, v in all_repairs.items() if k is not dropped)

        report = run_suite(cases, AgentVersion("v2.1-regression", partial))

        assert report.release_blocked
        assert [r.incident_id for r in report.regressions] == ["I-002"]
        assert "2 refund entries" in report.regressions[0].detail

    def test_every_guardrail_is_load_bearing(self, generated_cases) -> None:
        """Dropping any single guard must be caught by at least one case.

        A guard no case depends on is either untested or unnecessary.
        """
        cases = list(generated_cases.values())
        all_repairs = {c.verified_repair.kind: c.verified_repair for c in cases}

        for kind in all_repairs:
            partial = tuple(v for k, v in all_repairs.items() if k is not kind)
            report = run_suite(cases, AgentVersion(f"drop-{kind.value}", partial))

            assert report.release_blocked, f"dropping {kind.value} was caught by no case"

    def test_no_case_passes_vacuously(self, generated_cases) -> None:
        """Protected must mean the guard worked, not that the fault never fired.

        A case whose staged fault silently fails to occur would show a green tick
        while exercising nothing — the most dangerous possible failure mode for a
        release gate.
        """
        cases = list(generated_cases.values())
        repairs = tuple({c.verified_repair.kind: c.verified_repair for c in cases}.values())

        report = run_suite(cases, AgentVersion("v2.0", repairs))

        assert report.verdict == "RELEASE OK"
        assert report.vacuous == [], "a case passed without its fault occurring"
        assert all(r.fault_fired for r in report.results)

    def test_vacuous_pass_is_surfaced_in_the_summary(self, generated_cases) -> None:
        from aftermath.immunity.runner import CaseResult

        report = ImmunityReport(
            version="v",
            results=[
                CaseResult("RC-x", "I-x", protected=True, detail="ok", fault_fired=False)
            ],
        )

        assert report.vacuous
        assert "vacuous" in report.summary()

    def test_empty_suite_reports_no_cases(self) -> None:
        report = ImmunityReport(version="v0", results=[])

        assert report.verdict == "NO CASES"
        assert not report.release_blocked

    def test_summary_is_human_readable(self, generated_cases) -> None:
        report = run_suite(list(generated_cases.values()), AgentVersion.unrepaired())

        assert "protected" in report.summary()
        assert "RELEASE WARNING" in report.summary()


class TestVaultStorage:
    def test_store_and_reload_round_trips(self, generated_cases, tmp_path: Path) -> None:
        vault = ImmunityVault(tmp_path)
        case = generated_cases["I-001"]

        vault.store(case)

        assert vault.load(case.case_id) == case
        assert vault.load_all() == [case]

    def test_store_verifies_controls_before_admitting(
        self, generated_cases, tmp_path: Path
    ) -> None:
        """The vault must not accumulate cases that detect nothing."""
        vault = ImmunityVault(tmp_path)
        toothless = generated_cases["I-001"].model_copy(
            update={"scenario_id": "cancel_pending_order"}
        )

        with pytest.raises(CaseControlsFailed):
            vault.store(toothless)
        assert vault.load_all() == []

    def test_stored_case_is_valid_json_on_disk(
        self, generated_cases, tmp_path: Path
    ) -> None:
        vault = ImmunityVault(tmp_path)
        path = vault.store(generated_cases["I-002"])

        payload = json.loads(path.read_text(encoding="utf-8"))

        assert payload["verified_repair"]["kind"] == "idempotent_refund"
        assert payload["evidence_effect_size"] == 1.0

    def test_unknown_case_raises(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            ImmunityVault(tmp_path).load("RC-nope")

    def test_missing_directory_yields_no_cases(self, tmp_path: Path) -> None:
        assert ImmunityVault(tmp_path / "absent").load_all() == []

    def test_repairs_of_record_covers_every_case(
        self, generated_cases, tmp_path: Path
    ) -> None:
        vault = ImmunityVault(tmp_path)
        for case in generated_cases.values():
            vault.store(case)

        repairs = vault.repairs_of_record()

        report = run_suite(vault.load_all(), AgentVersion("of-record", repairs))
        assert report.verdict == "RELEASE OK"

    def test_committed_vault_is_loadable_and_green(self) -> None:
        """The vault checked into the repository must itself be valid."""
        cases = ImmunityVault().load_all()

        assert cases, "no regression cases are committed"
        for case in cases:
            verify_case_controls(case)


class TestUnrepairableIncidentIsNotForced:
    def test_i005_has_no_repair_so_no_case_exists(self) -> None:
        """I-005 cannot become an immunity case, and must not be given a fake one.

        No intervention prevents it — correcting the policy read only swaps the
        failure for an under-refund — so there is no evidenced cause and no
        repair to verify. A case built anyway would record a guardrail as a fix
        for something it does not fix.
        """
        report = ForensicOrchestrator(None, trials=TRIALS).investigate(INCIDENTS["I-005"])

        assert report.root_cause_step is None
        assert not report.repair_accepted
        assert "I-005" not in {c.incident_id for c in ImmunityVault().load_all()}

    def test_forcing_a_blocking_repair_is_refused_by_the_controls(self) -> None:
        """A guardrail that blocks everything cannot be smuggled into the vault.

        `block_all_refunds` refuses every refund, so on I-005 the run still
        fails — now by under-refunding rather than over-refunding. The controls
        reject the case rather than recording a broken guardrail as a fix.
        """
        case = build_case(
            INCIDENTS["I-005"],
            root_cause_step="s0007",
            verified_repair=RepairSpec(kind=RepairKind.BLOCK_ALL_REFUNDS),
            evidence_effect_size=1.0,
            evidence_artifact_hash="sha256:test",
        )

        with pytest.raises(CaseControlsFailed, match="does not prevent"):
            verify_case_controls(case)

    def test_a_blocking_guard_breaks_a_legitimate_refund(self) -> None:
        """Independent of any case: the guard is genuinely harmful."""
        from aftermath.injection.runner import NORMAL_CASES
        from aftermath.replay.repair import evaluate_repair

        evaluation = evaluate_repair(
            RepairSpec(kind=RepairKind.BLOCK_ALL_REFUNDS),
            scenario_id="refund_in_window",
            seed=1337,
            injection=None,
            normal_case_ids=NORMAL_CASES,
            trials=TRIALS,
        )

        assert evaluation.false_block_rate > 0
        assert not evaluation.acceptable


class TestGuardInteraction:
    """Guards that pass alone can be unsafe together.

    Found by the immunity suite in P8.3, not by inspection: with all guardrails
    applied, two cases regressed even though each passed with its own repair.
    """

    def test_ordering_a_value_fix_after_a_decision_is_unsafe(self) -> None:
        """The concrete failure: approval decided on an amount about to change.

        `rederive_approval` computes the approval requirement from a truncated
        refund amount; `bound_refund_to_order_total` then corrects the amount
        upward. Result: an over-limit refund with no approver — worse than the
        bug either guard fixes.
        """
        from aftermath.replay.repair import RepairKind, RepairSpec

        case = next(c for c in ImmunityVault().load_all() if c.case_id == "RC-I-013")
        bound = RepairSpec(kind=RepairKind.BOUND_REFUND_TO_ORDER_TOTAL)
        rederive = RepairSpec(kind=RepairKind.REDERIVE_APPROVAL)

        # GuardChain reorders, so build the unsafe sequence explicitly to show
        # what the precedence rule is protecting against.
        from aftermath.replay.repair import GUARD_PRECEDENCE

        assert (
            GUARD_PRECEDENCE["bound_refund_to_order_total"]
            < GUARD_PRECEDENCE["rederive_approval"]
        ), "value corrections must precede decisions derived from those values"

        safe = run_case(case, AgentVersion("ordered", (rederive, bound)))
        assert safe.protected, "the chain must reorder an unsafely-given sequence"

    def test_full_guard_set_protects_every_case(self) -> None:
        """The release gate that matters: all guards, all cases, together."""
        vault = ImmunityVault()
        cases = vault.load_all()

        report = run_suite(cases, AgentVersion("all-guards", vault.repairs_of_record()))

        assert report.verdict == "RELEASE OK", [r.detail for r in report.regressions]
        assert report.vacuous == []

    def test_precedence_is_total_over_the_library(self) -> None:
        """Every guard has a rank, or ordering silently falls back to arbitrary."""
        from aftermath.replay.repair import GUARD_PRECEDENCE, RepairKind

        assert {k.value for k in RepairKind} <= set(GUARD_PRECEDENCE)

    def test_ordering_is_stable_within_a_tier(self) -> None:
        from aftermath.replay.repair import RepairKind, RepairSpec, order_guards

        a = RepairSpec(kind=RepairKind.VALIDATE_POLICY_FRESHNESS)
        b = RepairSpec(kind=RepairKind.VALIDATE_POLICY_RESOLVES)

        assert order_guards((a, b)) == (a, b)
