# AFTERMATH — Project Status

**Last updated:** 2026-08-30
**Last verified commit:** `d654078` — feat: P3 fault injection and a 5-incident benchmark with ground truth

---

# Overall Completion: 32%

**Derivation.** Completion is the weighted sum of phase completion from `docs/PHASES.md`. It is never estimated by feel.

| Phase | Weight | % done | Contribution |
|---|---:|---:|---:|
| P0 Bootstrap & documentation | 4 | 100% | 4.0 |
| P1 Foundations | 10 | 100% | 10.0 |
| P2 Simulated company agent | 10 | 100% | 10.0 |
| P3 Fault injection & incidents | 8 | 100% | 8.0 |
| P4 Replay engine ⚠ | 14 | 0% | 0.0 |
| P5 Minimal forensic pipeline (MVP) | 14 | 0% | 0.0 |
| P6 Immunity Vault | 8 | 0% | 0.0 |
| P7 Baseline & benchmark | 10 | 0% | 0.0 |
| P8 Swarm expansion & agent-count study | 10 | 0% | 0.0 |
| P9 Frontend | 8 | 0% | 0.0 |
| P10 Hardening & demo | 4 | 0% | 0.0 |
| P11 TEE vault *(optional, unweighted)* | 0 | 0% | 0.0 |
| **Total** | **100** | | **32.0** |

Within a phase, % done = satisfied acceptance criteria ÷ total acceptance criteria for that phase.

---

## Current phase

**P3 — Fault injection & incidents with ground truth.** Complete. All 4 acceptance criteria verified.

## Current objective

Begin **P4 — Deterministic replay engine + counterfactual interventions**. ⚠ Highest-risk phase: if byte-identical strict replay proves impossible, the project's central premise needs rethinking, and that finding must be recorded rather than worked around.

## Completed phases

- **P0** — documentation system, CLAUDE.md, phases, architecture, testing strategy, status/context tracking, `.gitignore`, `.env.example`.
- **P1** — backend package, trace schema + content hashing, LLM provider abstraction (mock/gemini/recording), SQLite persistence + artifact store, FastAPI skeleton, 64-test pytest suite, import-boundary enforcement.
- **P2** — seeded simulated world (versioned policies), 7 simulated tools, `CompanyAgent` adapter + custom-loop agent (D-004 resolved), trace collector, 5 clean scenarios with deterministic oracles.
- **P3** — injection framework (tool-result, world-state, retry layers), incident definition format + loader, **5 incidents** with injector-authored ground truth, normal-case set.

## Active tasks

- None in progress.

## Blocked tasks

- **Gemini API key** — not yet configured. Not blocking: P3–P4 run entirely on the deterministic mock provider. A key in `.env` is needed before P5 runs the forensic pipeline against a real model.

## Next tasks (in order)

1. **P4.1** — replay a stored trace with world-state restoration; assert byte-identical strict replay. **Do this first** — it is the make-or-break result.
2. **P4.2** — `InterventionSpec`: replace tool result, alter world state, drop/reorder step, force policy or approval outcome.
3. **P4.3** — N-trial experiment runner + deterministic outcome scoring against scenario oracles.
4. **P4.4** — effect-size computation and hypothesis ranking.
5. **P4.5** — positive control (intervene at `true_causal_step` → failure rate drops) and negative control (unrelated step → no change); experiment artifacts persisted.

## Failing tests

None. **260 passed** (`pytest backend/tests -q`, 0.63s).

## Known bugs

None known.

## Technical debt

- `replay/`, `immunity/`, `benchmark/`, `forensics/` are still empty package stubs. The import-boundary test over them therefore passes with nothing to inspect; the detector itself is verified against synthetic violating trees, and the check becomes load-bearing in P4.
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
- `main` tracks `origin/main`; pushed and verified at `d654078`.
- Bootstrap commit: `c6825fb` ✅
- Push policy: no force push, no history rewrite. Push only after a phase's Definition of Done is met.
