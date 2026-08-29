# AFTERMATH — Session Context & Handoff

**Purpose:** if the session ends or context resets, this file alone (plus the docs it points to) must be enough to continue accurately. Written for a reader who remembers nothing.

**Last updated:** 2026-08-30 — end of P3.
**Current phase:** P3 complete → next is **P4 Deterministic replay engine** ⚠ (highest-risk phase).

---

## What was completed this cycle

**P3 — controlled failures with trustworthy ground truth.**

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

- `pytest backend/tests -q` → **260 passed** in ~0.63s, fully offline.
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

.venv/bin/python -m pytest backend/tests -q                  # 180 passed
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

**P4.1 — prove byte-identical strict replay, before building anything else on top of it.**

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
