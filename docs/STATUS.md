# AFTERMATH — Project Status

**Last updated:** 2026-08-30
**Last verified commit:** `8786685` — feat: P8.2 agent-count sweep

---

# Overall Completion: 88%

**Derivation.** Completion is the weighted sum of phase completion from `docs/PHASES.md`. It is never estimated by feel.

| Phase | Weight | % done | Contribution |
|---|---:|---:|---:|
| P0 Bootstrap & documentation | 4 | 100% | 4.0 |
| P1 Foundations | 10 | 100% | 10.0 |
| P2 Simulated company agent | 10 | 100% | 10.0 |
| P3 Fault injection & incidents | 8 | 100% | 8.0 |
| P4 Replay engine ⚠ | 14 | 100% | 14.0 |
| P5 Minimal forensic pipeline (MVP) | 14 | 100% | 14.0 |
| P6 Immunity Vault | 8 | 100% | 8.0 |
| P7 Baseline & benchmark | 10 | 100% | 10.0 |
| P8 Swarm expansion & agent-count study | 10 | 100% | 10.0 |
| P9 Frontend | 8 | 0% | 0.0 |
| P10 Hardening & demo | 4 | 0% | 0.0 |
| P11 TEE vault *(optional, unweighted)* | 0 | 0% | 0.0 |
| **Total** | **100** | | **88.0** |

Within a phase, % done = satisfied acceptance criteria ÷ total acceptance criteria for that phase.

---

## Current phase

**P8 — Swarm expansion & agent-count study.** Complete.

**P8.1 result: the sweep fallback lifted AFTERMATH 0.75 → 0.90, now TIED with the baseline.** Measured against the P7 cassette so agent answers were identical and the change is attributable to the orchestration alone. The agent pipeline still does not beat the deterministic sweep (0.95).

**⚠ THE BASELINE WON: 0.90 vs 0.75 on the primary metric.** Published as measured (D-007). The informative part: AFTERMATH's *deterministic* configuration scores **0.95**, beating the baseline. The replay machinery works; the LLM agent layer is a net negative because it narrows the hypothesis set below what the evidence engine needs.

**P8.3 result: repair coverage 10/20 → 16/20**, and the immunity suite caught a **guard interaction that was less safe than either guard alone** — `rederive_approval` deciding on an amount `bound_refund_to_order_total` was about to correct, issuing an unapproved over-limit refund. Fixed by making guard precedence explicit.

**P8.2 result: more investigators raise recall (0.70 → 0.80 → 0.85) at 3.07× then 1.66× the tokens — and buy nothing the deterministic fallback does not already provide free.** Production configuration: **1 investigator**. The swarm was not expanded, because the measurement did not justify it (D-008, D-021).

## Current objective

Begin **P9 — Frontend**: Incident Lab, Evidence Board, Replay Lab, Repair Tournament, Immunity Vault. Hard rule from the outset — every displayed value reads from a stored artifact in `data/results/` or the API, and any "running" indicator maps to real backend state.

## Completed phases

- **P0** — documentation system, CLAUDE.md, phases, architecture, testing strategy, status/context tracking, `.gitignore`, `.env.example`.
- **P1** — backend package, trace schema + content hashing, LLM provider abstraction (mock/gemini/recording), SQLite persistence + artifact store, FastAPI skeleton, 64-test pytest suite, import-boundary enforcement.
- **P2** — seeded simulated world (versioned policies), 7 simulated tools, `CompanyAgent` adapter + custom-loop agent (D-004 resolved), trace collector, 5 clean scenarios with deterministic oracles.
- **P3** — injection framework (tool-result, world-state, retry layers), incident definition format + loader, **5 incidents** with injector-authored ground truth, normal-case set.
- **P4** — deterministic replay engine, counterfactual interventions, N-trial experiment runner, effect-size ranking. Byte-identical strict replay verified; 4/5 correct root-cause localization under a strong (healthy-value) control.
- **P5** — 4 runtime agents (investigator, planner, repair, verifier) + orchestrator; redaction; measurement-based cause/consequence separation (`replay/chain.py`); repair guard library with prevention **and** false-block evaluation. 5/5 localization deterministically and with live agents.
- **P6** — regression cases with two-direction controls, immunity vault, composable guard chains, suite runner and release gate. Reintroduced-bug detection verified.
- **P7** — incident set 5→20 (all verified), scenarios enforce full invariant sets, fair single-LLM baseline (fairness review D-017), deterministic grader with near-miss handling, metrics from stored artifacts, live benchmark run. **Result: baseline 0.90, AFTERMATH-with-agents 0.75, AFTERMATH-deterministic 0.95.**

## Active tasks

- None in progress.

## Blocked tasks

**Nothing is blocked.**

- **Gemini API key** — ✅ configured in `.env` (gitignored, mode 600) since P7. Used for every live run: the P5 pipeline, the P7 benchmark, and the P8.2 sweep (~500 calls total). The default test suite never touches it — an autouse fixture isolates tests from `.env` (D-013), so `pytest` behaves identically with or without a key present.
- **Reproducing published results needs no key.** Committed cassettes replay the benchmark offline to the same artifact hash, asserted by test.

## Next tasks (in order)

1. ~~**P8.1** — sweep fallback.~~ Done: 0.75 → 0.90, before/after published.
2. **P8.2** — investigator-count sweep (1/3/5/7) against the 0.95 deterministic ceiling, measuring accuracy, latency, and token cost.
3. ~~**P8.3** — add `bound_refund_to_order_total`.~~ Done: 10/20 → 16/20, before/after published; found and fixed a guard-ordering safety bug.
4. ~~**P8.4/P8.5** — decide the production configuration on measurement.~~ Done: 1 investigator, recorded as D-021.
5. **P9.1** — read-only UI over the committed artifacts (benchmark results, incident set, immunity vault) before anything live.

## Failing tests

None. **832 passed** offline (`pytest backend/tests -q`, ~5.2s), plus 5 opt-in `live` tests.

## Known bugs

None known.

## Technical debt

- `benchmark/` is still an empty package stub.
- **The agent layer no longer subtracts, but still does not add.** P8.1 lifted it 0.75 → 0.90 (tied with the baseline), yet AFTERMATH's deterministic sweep alone still scores 0.95. The residual gap is one step-labelling case (I-010).
- **All wrong answers across both systems are call-step vs result-step of the same call.** A labelling ambiguity, not a different diagnosis. Strict convention retained; the lenient alternative helps the baseline more (1.00 vs 0.80), and both numbers are published.
- **The immunity suite has 16 cases, not 20.** Four incidents have no acceptable repair: I-005 (no localizable cause) and I-009/I-014/I-020, which corrupt *eligibility* rather than an amount. A `rederive_eligibility` guard would likely cover the latter three — **deliberately not added**, since adding guards until the benchmark is fully covered is the fitting D-019 prevents.
- **Guard ordering is safety-critical.** Value-correcting guards must precede decision-deriving ones; `GuardChain` enforces this on construction. Found by the suite, not by inspection.
- **I-005 is not localizable and reports no cause.** Correcting the policy read swaps one failure for another (the agent then under-refunds). This corrects P5's reported 5/5 to 19/20 — the earlier success was an artifact of a narrow oracle. The import-boundary guard is load-bearing for `replay/` and now also covers the deterministic chain and repair modules.
- **Repairs are selected from a fixed guard library, not synthesized.** The agent chooses a kind; Python applies and measures it. Keeps repairs executable, but narrows what "the agent proposes a repair" means.
- **I-005 has no acceptable repair in the library.** A freshness check cannot fix a world that genuinely lacks the newer policy. Reported honestly (`repair_accepted: false`) rather than promoting the blocker.
- **Live cassettes are gitignored**, so the live agent result is not reproducible from a clean clone. Committing benchmark cassettes is a P7 task.
- **Live "unique effect" partly reflects narrower hypothesis sets**, not better discrimination: agents proposed 1–2 candidates, so ties often never formed.
- **Scenarios now enforce full invariant sets.** Previously each was judged by one oracle, so a run could violate a different safety property and still pass. Strengthening this expanded the injectable fault surface from 2 to 20 viable incidents — and invalidated one published number (see CHANGELOG).
- **Effect-size ties: partly resolved in P5.** `replay/chain.py` now separates cause from consequence by *measurement* (does correcting A normalize B?), resolving I-001 and I-004. I-005 remains unresolvable that way — a world-state fault — and its report is explicitly labelled `earliest_step_heuristic`. The heuristic still exists; it is now the labelled fallback rather than the default.
- **The intervention vocabulary bounds what is findable.** I-002's fix is skipping a duplicated call, so no value-replacement experiment reaches it and `localize()` correctly returns `None`. With `SKIP_TOOL_CALL` it localizes at +1.00 — so the planner's choice of intervention *kind* is load-bearing, not incidental.
- **Failure rates are 0.0 or 1.0 with zero variance**, because the agent's control flow is deterministic. Real agents will produce intermediate rates; `TrialSummary.distinct_traces` tracks trace variance so that shift is visible rather than silent.
- ~~P4's interventions were written by us, not proposed by a model.~~ Resolved in P5: live agents proposed all hypotheses and the planner chose `skip_tool_call` for the retry fault unaided.
- The MVP agent's control flow is deterministic Python; the model narrates reasoning but does not decide. Deliberate (D-003), but it means agent-reasoning failure modes cannot be injected at the model level.
- **The CONTEXT injection layer is taxonomy only — no kind implements it.** `calculate_refund` re-reads the customer from world state rather than using what `get_customer` returned, so altering that call's arguments changes nothing the agent decides. Revisit when the agent's data flow deepens.
- All 5 incidents currently fail at rate 1.0 because the agent is fully deterministic. The rate is *measured*, not assumed, so it stays honest when P4 introduces resampled replay.
- `RecordingProvider` rewrites the whole cassette on each new response — fine at current volume, revisit if cassettes grow large.
- Watch items: SQLite → PostgreSQL migration seam; artifact store is local filesystem only.

## Benchmark status

**Run 2026-08-30.** 20 incidents, `gemini-3.7-flash`, identical set and grader for both systems.

| configuration | localization | exact | wrong | abstained |
|---|---:|---:|---:|---:|
| AFTERMATH, deterministic sweep | **0.95** | 19 | 0 | 1 |
| Baseline, single LLM | **0.90** | 18 | 2 | 0 |
| AFTERMATH, live LLM agents (P7) | 0.75 | 15 | 1 | 4 |
| **AFTERMATH, live agents + sweep fallback (P8.1)** | **0.90** | 18 | 1 | 1 |

Artifacts: `data/results/benchmark.json`, `data/results/benchmark_deterministic.json`. Every number above is read from those files.

**The baseline beats the agent pipeline.** AFTERMATH's deficit is entirely abstentions — it refuses to answer without evidence, and the metric does not penalize guessing. The deterministic configuration beating the baseline is what localizes the weakness to the agent layer.

## Agent-count study (P8.2)

| investigators | recall | tokens/incident |
|---:|---:|---:|
| **1 (production)** | 0.70 | **2,093** |
| 3 | 0.80 | 6,424 |
| 5 | 0.85 | 10,694 |

Artifact: `data/results/investigator_recall_sweep.json`. Recall rises but does not convert into localization, because the exhaustive fallback already floors it. **Not measured:** whether 3/5 investigators change end-to-end localization — a follow-up costing ~300 live calls.

## Runtime-agent status

**4 runtime agents implemented** (P5): investigator, counterfactual planner, repair, verifier — prompts in `forensics/prompts/`, strict Pydantic I/O, ground truth redacted. Verified contributing against a live model (5/5 agent-sourced hypotheses). The full ~16-agent swarm is P8 and contingent on measurement. Note: the *monitored* company agent (P2) is the subject of forensics, not a forensic agent.

## UI status

**Not started** (P9). Deliberately sequenced after the evidence pipeline works.

## Security / TEE status

- Secrets handling: `.env` gitignored, `.env.example` with placeholders only. ✅ in place.
- TEE / Secure Forensic Vault: **not implemented, optional, P11.** No TEE, attestation, or confidential-computing claim may appear anywhere in this project until real attestation output exists.

## Deployment status

**Not deployed.** Local development only. Docker is P10.

## Git / remote status

- Repository: initialized, branch `main`.
- Remote: **`origin` → https://github.com/tony19053000/AFTERMATH.git** ✅ configured 2026-08-30.
- Remote was empty at first push (0 refs) — no pre-existing history was overwritten.
- `main` tracks `origin/main`; pushed and verified at `8786685`.
- Bootstrap commit: `c6825fb` ✅
- Push policy: no force push, no history rewrite. Push only after a phase's Definition of Done is met.
