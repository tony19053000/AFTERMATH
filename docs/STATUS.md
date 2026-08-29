# AFTERMATH — Project Status

**Last updated:** 2026-08-30
**Last verified commit:** `c6825fb` — docs: bootstrap AFTERMATH project documentation system

---

# Overall Completion: 24%

**Derivation.** Completion is the weighted sum of phase completion from `docs/PHASES.md`. It is never estimated by feel.

| Phase | Weight | % done | Contribution |
|---|---:|---:|---:|
| P0 Bootstrap & documentation | 4 | 100% | 4.0 |
| P1 Foundations | 10 | 100% | 10.0 |
| P2 Simulated company agent | 10 | 100% | 10.0 |
| P3 Fault injection & incidents | 8 | 0% | 0.0 |
| P4 Replay engine ⚠ | 14 | 0% | 0.0 |
| P5 Minimal forensic pipeline (MVP) | 14 | 0% | 0.0 |
| P6 Immunity Vault | 8 | 0% | 0.0 |
| P7 Baseline & benchmark | 10 | 0% | 0.0 |
| P8 Swarm expansion & agent-count study | 10 | 0% | 0.0 |
| P9 Frontend | 8 | 0% | 0.0 |
| P10 Hardening & demo | 4 | 0% | 0.0 |
| P11 TEE vault *(optional, unweighted)* | 0 | 0% | 0.0 |
| **Total** | **100** | | **24.0** |

Within a phase, % done = satisfied acceptance criteria ÷ total acceptance criteria for that phase.

---

## Current phase

**P2 — Simulated company agent, world, and tools.** Complete. All 5 acceptance criteria verified.

## Current objective

Begin **P3 — Fault injection & incidents with ground truth**: injection framework, incident definition format, first 3–5 incidents, normal-case set for later false-positive measurement.

## Completed phases

- **P0** — documentation system, CLAUDE.md, phases, architecture, testing strategy, status/context tracking, `.gitignore`, `.env.example`.
- **P1** — backend package, trace schema + content hashing, LLM provider abstraction (mock/gemini/recording), SQLite persistence + artifact store, FastAPI skeleton, 64-test pytest suite, import-boundary enforcement.
- **P2** — seeded simulated world (versioned policies), 7 simulated tools, `CompanyAgent` adapter + custom-loop agent (D-004 resolved), trace collector, 5 clean scenarios with deterministic oracles.

## Active tasks

- None in progress.

## Blocked tasks

- **Gemini API key** — not yet configured. Not blocking: P3–P4 run entirely on the deterministic mock provider. A key in `.env` is needed before P5 runs the forensic pipeline against a real model.

## Next tasks (in order)

1. **P3.1** — injection framework with hooks at the tool-result, world-state, context, and policy layers.
2. **P3.2** — incident definition format + loader validating against the ground-truth schema.
3. **P3.3** — first 3 incidents: stale policy retrieval, duplicate refund after retry, human-approval bypass.
4. **P3.4** — normal-case set (the 5 clean scenarios) for later false-positive measurement.
5. **P3.5** — reproducibility tests: each incident fails at a stable rate; clean runs still pass.

## Failing tests

None. **180 passed** (`pytest backend/tests -q`, 0.54s).

## Known bugs

None known.

## Technical debt

- `replay/`, `immunity/`, `benchmark/`, `forensics/`, `injection/` are still empty package stubs. The import-boundary test over them therefore passes with nothing to inspect; the detector itself is verified against synthetic violating trees, and the check becomes load-bearing in P4.
- The MVP agent's control flow is deterministic Python; the model narrates reasoning but does not decide. Deliberate (D-003) and documented in the module, but it means agent-reasoning failure modes cannot yet be injected at the model level — P3 injects at the tool, state, context, and policy layers instead.
- `RecordingProvider` rewrites the whole cassette on each new response — fine at current volume, revisit if cassettes grow large.
- Watch items: SQLite → PostgreSQL migration seam; artifact store is local filesystem only.

## Benchmark status

**Not started** (P7). No incidents, no baseline, no metrics. **No benchmark numbers exist anywhere in this repository, and none may be quoted until P7 produces stored artifacts.**

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
- `main` tracks `origin/main`; pushed and verified at `db9c9e7`.
- Bootstrap commit: `c6825fb` ✅
- Push policy: no force push, no history rewrite. Push only after a phase's Definition of Done is met.
