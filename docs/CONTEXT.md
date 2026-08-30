# AFTERMATH — Session Context & Handoff

**Purpose:** if the session ends or context resets, this file alone (plus the docs it points to) must be enough to continue accurately. Written for a reader who remembers nothing.

**Last updated:** 2026-08-30 — end of P6.
**Current phase:** P6 complete → next is **P7 Fair baseline + benchmark**.

---

## What was completed this cycle

**P6 — the Immunity Vault.** A fixed failure can no longer come back silently.

- `immunity/case.py` — `RegressionCase` + `build_case`. Takes primitives, not a forensic report: `immunity/` and `forensics/` are siblings, and the vault must not depend on *how* a diagnosis was reached, only on what was proven.
- `immunity/runner.py` — `AgentVersion` (agent + the guardrails it ships), suite runner, release gate.
- `immunity/vault.py` — JSON storage at `data/immunity/`, **committed** (unlike experiment artifacts, cases are durable records reviewable in a diff).
- `replay/repair.py` — `GuardChain` so multiple guardrails compose; a release accumulates them.

### The release gate, measured

| version | result |
|---|---|
| unrepaired *(control)* | **0/4 protected → RELEASE WARNING** |
| all guardrails | **4/4 protected → RELEASE OK** |
| idempotency guard dropped | **3/4 → RELEASE WARNING**, catches RC-I-002 |

Every guardrail is dropped in turn and asserted to be caught by at least one case.

**A case must be able to fail.** `vault.store()` admits nothing until it FAILS unrepaired and PASSES repaired. Both rejection paths are tested.

**Hole found in review:** "protected" did not distinguish *guard worked* from *fault never fired* — a green tick over an exercise of nothing. `CaseResult.fault_fired` / `ImmunityReport.vacuous` now surface it; verified no case passes vacuously.

**Only 4 cases, not 5.** I-005 has no acceptable repair, so it cannot become one. A test asserts its absence and shows why forcing it would be wrong: the blocking guard passes its own controls perfectly yet breaks a legitimate refund. Controls alone are insufficient; the false-block gate is what stops a broken guardrail being recorded as a fix.

---

### Earlier: P5 — the MVP vertical slice, closed. Incident → evidenced cause → tested repair.

- `forensics/schemas.py` — strict Pydantic I/O for all four agents.
- `forensics/parsing.py` — recovers JSON from fenced/preambled model output; raises `AgentOutputError` rather than guessing.
- `forensics/redaction.py` — **the single place agents are denied ground truth.** If an agent could see `true_causal_step`, every accuracy number would be meaningless.
- `forensics/agents.py` — Investigator, CounterfactualPlanner, RepairAgent, Verifier. Prompts are versioned files in `forensics/prompts/`, not inline strings, because they are experimental variables.
- `forensics/orchestrator.py` — wires proposals to measurement and builds the report.
- `replay/chain.py` — **discharges most of D-016**: separates cause from consequence by measurement (does correcting A normalize B?) instead of the earliest-step heuristic.
- `replay/repair.py` — guard library + evaluation on **two** axes: prevention rate and false-block rate.

### Results

**Deterministic path (no LLM): 5/5 localization.**

| incident | cause | resolution | repair | prevent | false-block | accepted |
|---|---|---|---|---:|---:|---|
| I-001 | s0007 ✅ | **dominance measured** | validate_policy_freshness | 1.00 | 0.00 | ✅ |
| I-002 | s0019 ✅ | unique effect | idempotent_refund | 1.00 | 0.00 | ✅ |
| I-003 | s0009 ✅ | unique effect | rederive_approval | 1.00 | 0.00 | ✅ |
| I-004 | s0007 ✅ | **dominance measured** | validate_policy_freshness | 1.00 | 0.00 | ✅ |
| I-005 | s0007 ✅ | earliest-step *heuristic* | *none acceptable* | 1.00 | 0.20 | ❌ |

**Live agents (`gemini-3.7-flash`, 263s): 5/5 localization, 5/5 agent-sourced hypotheses.** The fallback never fired. The planner chose `skip_tool_call` for I-002 unaided — the case value replacement structurally cannot reach.

`block_all_refunds` sits in the library deliberately as a plausible-looking bad option. It prevents 4/5 incidents and is rejected every time on false-block 0.20.

---

### Earlier: P4 — the replay engine. The highest-risk phase, and it passed.

- `replay/intervention.py` — `InterventionSpec`: replace a tool result, skip a call, suppress the injected fault. Step ids resolve to `(tool, occurrence)`.
- `replay/engine.py` — **deterministic re-execution, not playback** (D-014). Playback cannot answer a counterfactual: after an intervention the run must be free to diverge, and that divergence is the measurement.
- `replay/experiment.py` — N-trial runner, `effect_size = baseline_rate - intervened_rate`, ranking by effect size **only** (confidence is recorded and never consulted).
- The agent gained a pre-execution `override_call` hook, because post-hoc result rewriting cannot undo an action that already mutated state.

### Two results that matter

**1. Strict replay is byte-identical — via record/replay, not live re-execution.** Measured: running I-001 twice against a live model at `temperature=0.0` was *not* identical (narration diverged). Recording it and replaying from the cassette with no provider at all *was* identical. **Temperature 0 is not a determinism guarantee** (D-015).

**2. Localization is 4/5, not 5/5 — and the correction is instructive.** P4 was first reported as "5/5, perfect separation". That used a **tautological control**: each unrelated step replaced with *its own* value, a no-op that could never fail. Re-run with healthy-run values instead:

| incident | true cause | steps at full effect | localized |
|---|---|---|---|
| I-001 | s0007 | s0007, **s0009** (downstream) | ✅ |
| I-002 | s0019 | *none reachable by replacement* | ❌ None |
| I-003 | s0009 | s0009 | ✅ |
| I-004 | s0007 | s0007 | ✅ |
| I-005 | s0007 | s0007, **s0009** (downstream) | ✅ |

Effect size localizes the **causal chain**, not the unique root cause: correcting the stale policy *or* the wrong calculation it caused both prevent the failure. The earliest-tied-step tie-break is a **heuristic, not evidence** (D-016). I-002 is unreachable by value replacement — its fix is skipping a call — and the engine correctly returned `None` rather than guessing; with `SKIP_TOOL_CALL` it localizes at +1.00.

Both limitations are asserted in `TestCausalChainLimitations` so they cannot silently regress.

---

### Earlier: P3 — controlled failures with trustworthy ground truth

- `injection/spec.py` — `InjectionSpec`: kind, layer, target tool, occurrence. Layers: TOOL_RESULT, WORLD_STATE, RETRY (CONTEXT is taxonomy only — see limitations).
- `injection/injector.py` — applies the fault and **records the trace step it perturbed**. That recorded id is `true_causal_step`. Zero LLM imports.
- `injection/incidents.py` — definition schema + loader for `data/incidents/*.json`.
- `injection/runner.py` — runs incidents and clean cases; raises if a fault never fired.
- `data/incidents/` — **5 incidents** across 3 layers.
- The agent gained one injection point inside `_invoke`, so a fault can only enter where every tool call already passes.

### The 5 incidents (all verified failing their declared oracle)

| id | fault | layer | causal step | failing oracle |
|---|---|---|---|---|
| I-001 | stale policy served by the tool | tool_result | s0007 | refund_denied_outside_window |
| I-002 | duplicate refund after retry | retry | s0019 | no_duplicate_refund |
| I-003 | approval requirement suppressed | tool_result | s0009 | approval_required_above_limit |
| I-004 | policy labelled with a bogus version | tool_result | s0007 | refund_within_current_policy |
| I-005 | policy v2 missing from the world | world_state | s0007 | refund_denied_outside_window |

I-001 and I-005 reach the *same* outcome by different mechanisms (corrupt tool vs. wrong environment) and are deliberately kept separate — P4/P5 must be able to tell them apart.

---

### Earlier: P2 — the monitored system

- `companyagent/world.py` — seeded simulated world: customers, orders, **versioned** refund policies (v1 lenient / v2 strict, v2 effective from day 100), refund ledger. Time is an integer `day`, never a wall clock.
- `companyagent/tools.py` — the 7 simulated tools. Pure over world state; **no real side effects**. `issue_simulated_refund` is deliberately *not* idempotent — the duplicate-refund incident depends on that being possible.
- `companyagent/scenarios.py` — 5 clean scenarios + 5 deterministic oracles that judge **world state**, not the agent's narration.
- `companyagent/base.py` — the `CompanyAgent` protocol (the swap point).
- `companyagent/simple.py` — the MVP agent: a minimal custom loop (D-004).
- `tracing/collector.py` — owns step-id assignment and the parent chain, so an agent cannot emit an invalid trace.

**D-004 resolved:** minimal custom loop, **no ADK dependency**. Measured, not assumed — ADK pulls 37 packages and downgrades `websockets`, but the decisive reason is that its orchestration loop sits exactly where we need control for byte-identical replay. Full reasoning in `docs/DECISIONS.md`.

## What currently works

- `pytest backend/tests -q` → **417 passed** in ~1.9s, fully offline. Plus 5 opt-in `live` tests against the real model.
- All 5 incidents reproduce their failure at rate 1.00 (measured over 20 trials each).
- All 5 clean scenarios still PASS with no injection recorded.
- Identical seed → identical trace content hash **and** identical world state hash, verified across all 5 scenarios.
- Every state mutation appears in the trace; a denied refund traces zero mutations and leaves the world hash unchanged.
- `uvicorn aftermath.api.app:app` → `/health` 200.

## What is broken

Nothing known.

## What was tested

All 5 P2 acceptance criteria, each with a named test (mapped in `docs/TESTING.md` §5). Beyond the happy path: oracle negative controls (a duplicate refund, an unapproved large refund, and an over-refund under stale policy all correctly FAIL), tool error paths, failed cancels mutating nothing, and a static check that the tools module references no network or subprocess API.

## Important commands

```bash
uv venv --python 3.12 .venv                                  # python3 -m venv is broken here
uv pip install --python .venv/bin/python -e "backend[dev]"

.venv/bin/python -m pytest backend/tests -q                  # 417 passed
.venv/bin/python -m pytest backend/tests -m live -q          # 3 passed, needs GEMINI_API_KEY
.venv/bin/python -m uvicorn aftermath.api.app:app --port 8000
```

```python
# Run a monitored scenario
from aftermath.companyagent.world import build_world
from aftermath.companyagent.scenarios import get_scenario
from aftermath.companyagent.simple import SimpleCustomerOpsAgent
from aftermath.llm.mock import MockProvider
run = SimpleCustomerOpsAgent(MockProvider()).run(get_scenario("refund_in_window"), build_world())
```

## Important files

`core/trace.py` and `replay/` (P4) are the load-bearing pair: step ids and hashing are what replay verification and hypothesis addressing depend on. `tests/arch/test_import_boundaries.py` statically enforces AGENTS THINK / PYTHON TESTS.

## The seeded world, as it actually is (seed 1337, day 120)

Verified by inspection, not assumption — effective policy is **v2** (window 30d, auto-limit 20000, premium bonus 15d):

| order | tier | amount | status | age | in window | needs approval |
|---|---|---:|---|---:|---|---|
| ORD-2000 | premium | 33100 | delivered | 10 | yes | yes |
| ORD-2001 | standard | 30700 | delivered | 7 | yes | yes |
| ORD-2003 | premium | 17200 | shipped | 11 | yes | no |
| ORD-2007 | standard | 22100 | shipped | 6 | yes | yes |
| ORD-2008 | standard | 35400 | **pending** | 55 | no | yes |
| ORD-2011 | standard | 24900 | delivered | 67 | no | yes |

ORD-2008 is the only `pending` order (the sole cancellable one). ORD-2011 is cleanly out-of-window under v2 but **in**-window under v1 — that gap is the stale-policy incident P3 will inject.

## Active assumptions

- Python 3.12.3, Node 22.22.1, git 2.43, `uv` available (verified). `python3 -m venv` is broken (no `ensurepip`).
- Gemini API key not supplied — P4 runs entirely on the mock provider; ground truth needs no provider at all.
- Remote: `origin` → https://github.com/tony19053000/AFTERMATH.git; `main` tracks `origin/main`.

## Next recommended task

**P7 — the fair baseline and the benchmark.** This is the phase that decides whether the project's central claim holds.

Start with **P7.1**: a single-LLM baseline given the same trace, the same output schema, a genuinely well-written prompt, and the same model. D-007 is a methodology commitment — a strawman baseline invalidates everything, and the result gets published even if AFTERMATH loses. Record the fairness review in DECISIONS.

Then the deterministic grader (near-miss and adjacent-step handling matter: with causal chains, "s0009 instead of s0007" is a near miss, not a random error), expanding the incident set toward 15–20, and committing cassettes so a benchmark run is reproducible from a clean clone.

### Superseded: P6.1 — the Immunity Vault. Convert a verified P5 report into a permanent regression case, then prove the case works with two controls: it must **FAIL against the unrepaired agent** and **PASS against the repaired one**. Both asserted in Python. Everything needed already exists: `RepairSpec` + `RepairGuard` apply a fix, and the incident definitions carry scenario/seed/injection/oracle.

Then the suite runner against an arbitrary agent version, the release-gate report, and a deliberately reintroduced bug to confirm the suite catches it.

**Watch out:** I-005 has no acceptable repair, so it cannot yet become an immunity case. That is the correct behaviour — do not force one.

### Superseded: P4.1 — prove byte-identical strict replay

This is the make-or-break result of the whole project. Take a stored trace, restore world state, re-execute with every nondeterministic call served from the record, and assert the replayed trace's `content_hash()` equals the original's. The pieces are already in place: `Trace.content_hash()` excludes wall-clock fields precisely so this comparison is meaningful, `RecordingProvider` in REPLAY mode raises rather than re-sampling, and `world_snapshot_ref` is recorded on every state-changing call.

Then P4.2–P4.5: `InterventionSpec`, the N-trial runner, effect-size ranking, and the two controls that make the evidence trustworthy — intervening at `true_causal_step` must drop the failure rate, and intervening at an unrelated step must not.

**If byte-identical strict replay turns out to be impossible, stop and record it in DECISIONS + CHANGELOG.** A negative result here is a real finding; quietly weakening the definition of "replay" would invalidate every experiment built on it.

## Unresolved questions (need the project owner)

1. ~~GitHub repository URL~~ — resolved.
2. ~~Google ADK vs. custom loop~~ — resolved as D-004: custom loop.
3. Gemini API key placement in `.env` — needed before P5's live run.
4. Hackathon deadline and any required tech constraints — affects how far past P7 we scope.

## Warnings / traps for the next session

- **Do not reconfigure the Claude Code development agents.** `.claude/` is set up. Those four are *development* agents; the AFTERMATH runtime agents in `docs/PRODUCT_AGENTS.md` are a different thing entirely — and so is the *monitored* company agent built in P2.
- **Do not let an LLM decide an experimental outcome.** `tests/arch/test_import_boundaries.py` enforces this; if it starts failing, that is the alarm working.
- That boundary test still inspects **empty** stubs (`replay/`, `immunity/`, `benchmark/`, `forensics/`). Its green is not yet evidence about P4's engine — **P4 is when it finally matters.**
- **An injection that changes nothing is not an incident.** The wrong-customer fault fired correctly and altered no outcome, because `calculate_refund` re-reads the customer from world state. It was removed rather than shipped. Check that a new fault actually flips an oracle before adding it to the benchmark.
- `InjectionLayer.CONTEXT` is declared but unimplemented; a spec using it fails loudly via `run_incident`.
- **Verify assumptions about the seeded world by inspecting it.** Two of five scenarios were initially assigned to orders that did not have the properties assumed; the table above is ground truth, and P3's incidents depend on getting this right.
- **P4 (replay engine) is the highest-risk phase.** If byte-identical strict replay proves impossible, record it in DECISIONS + CHANGELOG rather than working around it quietly.
- **No invented numbers.** Nothing may quote a benchmark result until P7 writes real artifacts.
- **Ground truth comes from the fault injector, never from a model.**
- Traces and worlds are Pydantic models; `World` is mutable (agents change it) but `Trace` is frozen — mutate a trace via `model_copy(update=...)`.
