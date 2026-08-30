# AFTERMATH — Project Status

**Last updated:** 2026-08-30
**Last verified commit:** `2cdf053` — docs: record P9 commit hash in STATUS

---

# Overall Completion: 96%

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
| P8 Agent-count study | 10 | 100% | 10.0 |
| P9 Frontend | 8 | 100% | 8.0 |
| P10 Hardening & demo | 4 | 0% | 0.0 |
| P11 TEE vault *(optional, unweighted)* | 0 | 0% | 0.0 |
| **Total** | **100** | | **96.0** |

Within a phase, % done = satisfied acceptance criteria ÷ total acceptance criteria for that phase.

---

## Current phase

**P9 — Frontend.** Complete. A read-only console served by our own backend at `/`, showing only values fetched from stored artifacts.

## Current objective

**P10 — Hardening, reproducibility, demo.** Docker, clean-clone reproduction, a secrets scan over full history, README verified against artifacts, and an honest limitations section.

## Where the project actually stands

The full loop runs end to end: **incident → evidenced cause → tested repair → permanent regression case → release gate.**

The central claim is **partially supported, and the qualification matters**. Counterfactual replay beats a capable LLM (0.95 vs 0.90). The LLM agent layer on top of it does not: alone it scored 0.75, and after the P8.1 fallback fix it ties the baseline at 0.90 — still below the deterministic engine it sits on.

## Completed phases

- **P0** — documentation system, CLAUDE.md, 11-phase plan, weighted completion tracking.
- **P1** — backend package, trace schema + content hashing, LLM provider abstraction (mock/gemini/recording), SQLite persistence + artifact store, FastAPI skeleton, import-boundary enforcement.
- **P2** — seeded simulated world (versioned policies), 7 simulated tools, `CompanyAgent` adapter + custom-loop agent (D-004), trace collector, 5 scenarios with deterministic oracles.
- **P3** — injection framework (tool-result, world-state, retry layers), incident format + loader, incidents with injector-authored ground truth.
- **P4** — deterministic replay engine, counterfactual interventions, N-trial runner, effect-size ranking. **Byte-identical strict replay verified**, and proven achievable only via record/replay — a live model at temperature 0 is not reproducible (D-015).
- **P5** — 4 runtime agents + orchestrator, ground-truth redaction, measurement-based cause/consequence separation (`replay/chain.py`), repair guard library measured on prevention **and** false-block.
- **P6** — regression cases with two-direction controls, immunity vault, composable guard chains, suite runner, release gate.
- **P7** — incident set 5→20 (each verified), scenarios enforce full invariant sets, fair single-LLM baseline (fairness review D-017), deterministic grader with near-miss handling, live benchmark.
- **P8** — sweep fallback (0.75→0.90), repair coverage 10/20→16/20, guard-ordering safety fix, agent-count study concluding **1 investigator** (D-021).
- **P9** — read-only console (Benchmark, Incident Lab, Evidence Board, Agent Study, Immunity Vault). Tests assert it hard-codes no result, has no fallback data, loads nothing cross-origin, and that every path it fetches resolves.

## Active tasks

None in progress.

## Blocked tasks

**Nothing is blocked.**

- **Gemini API key** — ✅ configured in `.env` (gitignored, mode 600). Used for the P5 pipeline, P7 benchmark and P8.2 sweep (~500 calls). The default suite never touches it: an autouse fixture isolates tests from `.env` (D-013), so `pytest` behaves identically with or without a key.
- **Reproducing published results needs no key.** Committed cassettes replay the benchmark offline to the same artifact hash, asserted by test.

## Next tasks (in order)

1. ~~**P10.2/P10.3/P10.4** — secrets scan, security tests, docs-drift checker.~~ Done: 0 secret patterns in full history; 14 security tests; 13 docs tests that fail on real drift.
2. **P10.1** — Docker + compose; verify a clean clone reproduces the benchmark from committed cassettes.
3. **P10.5** — demo script driving the real console against real artifacts.

## Failing tests

None. **875 passed** offline (`pytest backend/tests -q`, ~7s), plus 5 opt-in `live` tests requiring a key.

## Known bugs

None known.

## Benchmark status

**Run 2026-08-30.** 20 incidents, `gemini-3.7-flash`, identical incident set and identical deterministic grader for both systems.

| configuration | localization | exact | wrong | abstained |
|---|---:|---:|---:|---:|
| AFTERMATH — deterministic sweep | **0.95** | 19 | 0 | 1 |
| AFTERMATH — agents + sweep fallback *(current)* | **0.90** | 18 | 1 | 1 |
| Baseline — single LLM | **0.90** | 18 | 2 | 0 |
| AFTERMATH — agents alone *(superseded, P7)* | 0.75 | 15 | 1 | 4 |

**Current verdict: TIED** between the agent pipeline and the baseline. AFTERMATH is wrong less often (1 vs 2) and abstains rather than guessing; the metric does not penalize guessing.

Under the lenient grading convention (either step of the correct call counts): AFTERMATH 0.95, baseline **1.00**. Both conventions are published because they disagree about who leads.

Artifacts: `data/results/benchmark.json`, `benchmark_deterministic.json`, `benchmark_p7_pre_fallback.json`. Every number above is read from those files.

## Agent-count study (P8.2)

| investigators | recall | tokens/incident |
|---:|---:|---:|
| **1 (production)** | 0.70 | **2,093** |
| 3 | 0.80 | 6,424 |
| 5 | 0.85 | 10,694 |

Recall rises (+0.10, then +0.05) at 3.07× then 1.66× the tokens — and buys only avoidance of the exhaustive fallback, which the deterministic engine already performs free. Production configuration is 1 investigator (D-021).

**Not measured:** whether 3/5 investigators change end-to-end localization. A follow-up costing ~300 live calls.

## Technical debt

**About the result**
- **The agent layer ties the baseline but does not beat the deterministic sweep** (0.90 vs 0.95). The residual gap is one step-labelling case (I-010), where the agent names the `tool_call` step and ground truth is the `tool_result` step of the same call.
- **I-005 is not localizable** and correctly reports `no_cause_found` with no repair. Correcting the policy read swaps one failure for another. This corrected P5's reported 5/5 to 19/20 — the earlier success was an artifact of a narrow oracle.
- **Failure rates are 0.0 or 1.0 with zero variance**, because the agent's control flow is deterministic. Real agents give intermediate rates; `TrialSummary.distinct_traces` makes that shift visible.

**About coverage**
- **The immunity suite has 16 cases, not 20.** I-005 has no localizable cause; I-009/I-014/I-020 corrupt *eligibility* rather than an amount, and no guard re-derives eligibility. A `rederive_eligibility` guard would likely cover them — **deliberately not added**, since adding guards until the benchmark is fully covered is the fitting D-019 prevents.
- **Repairs are selected from a fixed guard library, not synthesized.** The agent chooses a kind; Python applies and measures it.
- **The CONTEXT injection layer is taxonomy only.** `calculate_refund` re-reads the customer from world state, so altering that call's arguments changes nothing the agent decides.

**About the design**
- **Guard ordering is safety-critical.** Value-correcting guards must precede decision-deriving ones; `GuardChain` enforces this on construction. Found by the suite, not by inspection.
- **The intervention vocabulary bounds what is findable.** A duplicated action needs `skip_tool_call`; no value replacement reaches it.
- The MVP agent's control flow is deterministic Python; the model narrates but does not decide (D-003), so reasoning-level faults cannot be injected.
- `RecordingProvider` rewrites the whole cassette per new response — fine at current volume.
- Watch items: SQLite → PostgreSQL seam; artifact store is local filesystem only.

## Runtime-agent status

**4 runtime agents implemented** (P5): investigator, counterfactual planner, repair, verifier. Prompts are versioned files in `forensics/prompts/`, I/O is strict Pydantic, ground truth is redacted before an agent sees a trace.

**The ~16-agent swarm was not built.** P8.2 measured agent count and concluded 1 investigator (D-021); the design in `docs/PRODUCT_AGENTS.md` remains documented as a design, explicitly unbuilt, with that measurement as the reason.

Note: the *monitored* company agent (P2) is the subject of forensics, not a forensic agent.

## UI status

**Built** (P9). Five views at `http://127.0.0.1:8000/`, served by FastAPI. Deleting an artifact yields a 404 and the view reports it unavailable — verified by deleting `benchmark.json` and checking the response, not by assuming it.

## Security / TEE status

- Secrets: `.env` gitignored (mode 600), `.env.example` holds placeholders only.
- **Full git history scanned: 0 matches** for API keys, private keys, or tokens. `.env` has never been tracked. Asserted by `TestNoSecretsAnywhere`.
- Committed cassettes hold responses only — no headers, no key material. Asserted by test.
- **Prompt injection is inert against this agent**, and the reason is recorded honestly: its control flow is deterministic Python, so injected instruction text has nothing to act on. That is a property of the current simple agent (D-003), *not* a mitigation we built, and it stops holding the moment the monitored agent becomes model-driven. `TestInstructionTextCannotSteerTheAgent` asserts it so the assumption fails loudly if that changes.
- TEE / Secure Forensic Vault: **not implemented, optional, P11.** No TEE, attestation, or confidential-computing claim appears anywhere in this project, and none may until real attestation output exists.

## Deployment status

**Not deployed.** Local development only. Docker is P10.

## Git / remote status

- Repository: branch `main`, remote `origin` → https://github.com/tony19053000/AFTERMATH.git
- Remote was empty at first push (0 refs) — no pre-existing history was overwritten.
- `main` tracks `origin/main`, in sync at `2cdf053`.
- Bootstrap commit: `c6825fb`.
- Push policy: no force push, no history rewrite. Push only after a phase's Definition of Done is met.
