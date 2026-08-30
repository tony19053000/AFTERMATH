# AFTERMATH — Project Status

**Last updated:** 2026-08-30
**Last verified commit:** `235af15` — feat: P5 minimal forensic pipeline

---

# Overall Completion: 60%

**Derivation.** Completion is the weighted sum of phase completion from `docs/PHASES.md`. It is never estimated by feel.

| Phase | Weight | % done | Contribution |
|---|---:|---:|---:|
| P0 Bootstrap & documentation | 4 | 100% | 4.0 |
| P1 Foundations | 10 | 100% | 10.0 |
| P2 Simulated company agent | 10 | 100% | 10.0 |
| P3 Fault injection & incidents | 8 | 100% | 8.0 |
| P4 Replay engine ⚠ | 14 | 100% | 14.0 |
| P5 Minimal forensic pipeline (MVP) | 14 | 100% | 14.0 |
| P6 Immunity Vault | 8 | 0% | 0.0 |
| P7 Baseline & benchmark | 10 | 0% | 0.0 |
| P8 Swarm expansion & agent-count study | 10 | 0% | 0.0 |
| P9 Frontend | 8 | 0% | 0.0 |
| P10 Hardening & demo | 4 | 0% | 0.0 |
| P11 TEE vault *(optional, unweighted)* | 0 | 0% | 0.0 |
| **Total** | **100** | | **60.0** |

Within a phase, % done = satisfied acceptance criteria ÷ total acceptance criteria for that phase.

---

## Current phase

**P5 — Minimal forensic pipeline.** Complete. **The MVP vertical slice is closed:** incident → evidenced cause → tested repair. 5/5 localization on the deterministic path and 5/5 against live agents (5/5 agent-sourced hypotheses).

## Current objective

Begin **P6 — Immunity Vault**: convert a verified incident into a permanent regression case that fails against the unrepaired agent and passes against the repaired one, plus a suite runner and release gate.

## Completed phases

- **P0** — documentation system, CLAUDE.md, phases, architecture, testing strategy, status/context tracking, `.gitignore`, `.env.example`.
- **P1** — backend package, trace schema + content hashing, LLM provider abstraction (mock/gemini/recording), SQLite persistence + artifact store, FastAPI skeleton, 64-test pytest suite, import-boundary enforcement.
- **P2** — seeded simulated world (versioned policies), 7 simulated tools, `CompanyAgent` adapter + custom-loop agent (D-004 resolved), trace collector, 5 clean scenarios with deterministic oracles.
- **P3** — injection framework (tool-result, world-state, retry layers), incident definition format + loader, **5 incidents** with injector-authored ground truth, normal-case set.
- **P4** — deterministic replay engine, counterfactual interventions, N-trial experiment runner, effect-size ranking. Byte-identical strict replay verified; 4/5 correct root-cause localization under a strong (healthy-value) control.
- **P5** — 4 runtime agents (investigator, planner, repair, verifier) + orchestrator; redaction; measurement-based cause/consequence separation (`replay/chain.py`); repair guard library with prevention **and** false-block evaluation. 5/5 localization deterministically and with live agents.

## Active tasks

- None in progress.

## Blocked tasks

- **Gemini API key** — not yet configured. Not blocking: P3–P4 run entirely on the deterministic mock provider. A key in `.env` is needed before P5 runs the forensic pipeline against a real model.

## Next tasks (in order)

1. **P6.1** — regression case format: scenario + seed + injection + oracle + expected safe behaviour.
2. **P6.2** — generate a case from a verified P5 report; assert it FAILS against the unrepaired agent and PASSES against the repaired one.
3. **P6.3** — vault storage + suite runner against an arbitrary agent version.
4. **P6.4** — release-gate report (`n protected / m regressions → RELEASE WARNING`).
5. **P6.5** — reintroduce a fixed bug deliberately and confirm the suite catches it.

## Failing tests

None. **386 passed** offline (`pytest backend/tests -q`, ~2.1s), plus 5 opt-in `live` tests.

## Known bugs

None known.

## Technical debt

- `immunity/` and `benchmark/` are still empty package stubs. The import-boundary guard is load-bearing for `replay/` and now also covers the deterministic chain and repair modules.
- **Repairs are selected from a fixed guard library, not synthesized.** The agent chooses a kind; Python applies and measures it. Keeps repairs executable, but narrows what "the agent proposes a repair" means.
- **I-005 has no acceptable repair in the library.** A freshness check cannot fix a world that genuinely lacks the newer policy. Reported honestly (`repair_accepted: false`) rather than promoting the blocker.
- **Live cassettes are gitignored**, so the live agent result is not reproducible from a clean clone. Committing benchmark cassettes is a P7 task.
- **Live "unique effect" partly reflects narrower hypothesis sets**, not better discrimination: agents proposed 1–2 candidates, so ties often never formed.
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

**Not started** (P7). 5 incidents with ground truth now exist (P3), but there is no baseline and no metrics. **No benchmark numbers exist anywhere in this repository, and none may be quoted until P7 produces stored artifacts.**

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
- `main` tracks `origin/main`; pushed and verified at `235af15`.
- Bootstrap commit: `c6825fb` ✅
- Push policy: no force push, no history rewrite. Push only after a phase's Definition of Done is met.
