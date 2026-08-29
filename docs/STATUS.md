# AFTERMATH — Project Status

**Last updated:** 2026-08-30
**Last verified commit:** `a09eadb` — feat: P4 deterministic replay engine and counterfactual experiments

---

# Overall Completion: 46%

**Derivation.** Completion is the weighted sum of phase completion from `docs/PHASES.md`. It is never estimated by feel.

| Phase | Weight | % done | Contribution |
|---|---:|---:|---:|
| P0 Bootstrap & documentation | 4 | 100% | 4.0 |
| P1 Foundations | 10 | 100% | 10.0 |
| P2 Simulated company agent | 10 | 100% | 10.0 |
| P3 Fault injection & incidents | 8 | 100% | 8.0 |
| P4 Replay engine ⚠ | 14 | 100% | 14.0 |
| P5 Minimal forensic pipeline (MVP) | 14 | 0% | 0.0 |
| P6 Immunity Vault | 8 | 0% | 0.0 |
| P7 Baseline & benchmark | 10 | 0% | 0.0 |
| P8 Swarm expansion & agent-count study | 10 | 0% | 0.0 |
| P9 Frontend | 8 | 0% | 0.0 |
| P10 Hardening & demo | 4 | 0% | 0.0 |
| P11 TEE vault *(optional, unweighted)* | 0 | 0% | 0.0 |
| **Total** | **100** | | **46.0** |

Within a phase, % done = satisfied acceptance criteria ÷ total acceptance criteria for that phase.

---

## Current phase

**P4 — Deterministic replay engine + counterfactual interventions.** Complete. All 6 acceptance criteria verified. **The highest-risk phase passed: byte-identical strict replay works, and counterfactual evidence discriminates 5/5 with perfect separation.**

## Current objective

Begin **P5 — Minimal AFTERMATH forensic pipeline (the MVP vertical slice)**: 1 investigator, 1 counterfactual planner, 1 repair agent, 1 verifier, plus the orchestrator. This is the first phase where LLM agents enter the product.

## Completed phases

- **P0** — documentation system, CLAUDE.md, phases, architecture, testing strategy, status/context tracking, `.gitignore`, `.env.example`.
- **P1** — backend package, trace schema + content hashing, LLM provider abstraction (mock/gemini/recording), SQLite persistence + artifact store, FastAPI skeleton, 64-test pytest suite, import-boundary enforcement.
- **P2** — seeded simulated world (versioned policies), 7 simulated tools, `CompanyAgent` adapter + custom-loop agent (D-004 resolved), trace collector, 5 clean scenarios with deterministic oracles.
- **P3** — injection framework (tool-result, world-state, retry layers), incident definition format + loader, **5 incidents** with injector-authored ground truth, normal-case set.
- **P4** — deterministic replay engine, counterfactual interventions, N-trial experiment runner, effect-size ranking. Byte-identical strict replay verified; 5/5 correct root-cause localization with +1.00 vs +0.00 separation.

## Active tasks

- None in progress.

## Blocked tasks

- **Gemini API key** — not yet configured. Not blocking: P3–P4 run entirely on the deterministic mock provider. A key in `.env` is needed before P5 runs the forensic pipeline against a real model.

## Next tasks (in order)

1. **P5.1** — investigator agent: read a trace, emit hypotheses bound to step ids, strict Pydantic output.
2. **P5.2** — counterfactual planner: hypothesis → executable `InterventionSpec` (the P4 vocabulary already exists).
3. **P5.3** — orchestrator wiring investigation → experiment → ranking, with agent output validated and malformed output handled.
4. **P5.4** — repair agent + deterministic repair evaluation (prevention rate on the incident, false-block rate on the 5 normal cases).
5. **P5.5** — verifier + synthesizer report citing experiment artifacts; persist the full pipeline run.

## Failing tests

None. **322 passed** offline (`pytest backend/tests -q`, ~1.0s), plus 3 opt-in `live` tests.

## Known bugs

None known.

## Technical debt

- `immunity/`, `benchmark/`, `forensics/` are still empty package stubs. The import-boundary guard is now load-bearing for `replay/` (493 lines, verified to fail on a deliberate violation).
- **Failure rates are 0.0 or 1.0 with zero variance**, because the agent's control flow is deterministic. Effect sizes are correspondingly clean (+1.00 / +0.00). Real agents will produce intermediate rates; `TrialSummary.distinct_traces` tracks trace variance so that shift is visible rather than silent.
- P4's corrective interventions are written by us from the trace and a clean run, not proposed by a model. Whether an LLM proposes them unaided is untested until P5 — the harder problem.
- The MVP agent's control flow is deterministic Python; the model narrates reasoning but does not decide. Deliberate (D-003), but it means agent-reasoning failure modes cannot be injected at the model level.
- **The CONTEXT injection layer is taxonomy only — no kind implements it.** `calculate_refund` re-reads the customer from world state rather than using what `get_customer` returned, so altering that call's arguments changes nothing the agent decides. Revisit when the agent's data flow deepens.
- All 5 incidents currently fail at rate 1.0 because the agent is fully deterministic. The rate is *measured*, not assumed, so it stays honest when P4 introduces resampled replay.
- `RecordingProvider` rewrites the whole cassette on each new response — fine at current volume, revisit if cassettes grow large.
- Watch items: SQLite → PostgreSQL migration seam; artifact store is local filesystem only.

## Benchmark status

**Not started** (P7). 5 incidents with ground truth now exist (P3), but there is no baseline and no metrics. **No benchmark numbers exist anywhere in this repository, and none may be quoted until P7 produces stored artifacts.**

## Runtime-agent status

**Not implemented** (P5). Design only — see `docs/PRODUCT_AGENTS.md`. Note: the *monitored* company agent now exists (P2), but it is the subject of forensics, not a forensic agent. MVP target is 4 runtime agents (investigator, counterfactual planner, repair, verifier); the full ~16-agent swarm is P8 and contingent on measurement.

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
- `main` tracks `origin/main`; pushed and verified at `a09eadb`.
- Bootstrap commit: `c6825fb` ✅
- Push policy: no force push, no history rewrite. Push only after a phase's Definition of Done is met.
