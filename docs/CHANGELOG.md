# AFTERMATH — Change & Experiment Log

The improvement history of this project. Every meaningful experiment is recorded here **whether it succeeded or failed** — a failed experiment that was correctly abandoned is as much a result as a successful one, and hiding it would misrepresent how the system was built.

Format per entry:

**WHAT WE TRIED** · **WHY** · **RESULT / EVIDENCE** (with the artifact path) · **DECISION: KEEP / MODIFY / REMOVE**

Rules: no entry may cite a number that is not in a stored artifact. Prompt changes, agent-count sweeps, model swaps, and replay-strategy changes all count as experiments.

---

## 2026-08-30 — Project bootstrap

**WHAT WE TRIED.** Established the persistent development system before writing any application code: git repository, `CLAUDE.md` operating manual, nine documentation files, an 11-phase development plan with weighted completion tracking, a testing strategy, and repository hygiene (`.gitignore`, `.env.example`).

**WHY.** This project spans many sessions and Claude Code loses conversation context between them. Without a repository-resident source of truth, later sessions re-derive decisions, reverse them, or drift from the objective. Bootstrapping first is cheaper than recovering from drift later.

**RESULT / EVIDENCE.** Documentation set complete and self-review for contradictions passed (checked: MVP vs. future scope separation, agents-vs-deterministic-software boundary, framework replaceability, baseline fairness, TEE deferred and unclaimable, frontend sequenced after the evidence pipeline). No code, no tests, no metrics — correct for this phase. Artifacts: the repository itself at the bootstrap commit.

**DECISION: KEEP.**

---

## 2026-08-30 — P1 Foundations

**WHAT WE TRIED.** Built the backend skeleton: trace schema with content hashing, LLM provider abstraction with record/replay, SQLite persistence with an immutable artifact store, FastAPI skeleton, and a 64-test suite including a static import-boundary guard.

**WHY.** Every later phase depends on these. Two choices were made deliberately rather than by default:

- **Semantic hashing excludes wall-clock fields.** The same scenario replayed with the same seed must hash identically, otherwise P4 cannot use hash comparison to verify replay fidelity. A clock-sensitive hash would have been useless for the one job it exists to do.
- **Replay misses raise instead of falling back to a live call.** A cassette miss silently re-sampling would make a "replay" nondeterministic while still calling itself a replay — quietly invalidating any evidence built on it.

**RESULT / EVIDENCE.** `pytest backend/tests -q` → **64 passed** in 0.45s, fully offline. `GET /health` → 200 verified against a real uvicorn server, not only TestClient. All 6 P1 acceptance criteria have named tests (mapped in `docs/TESTING.md` §5).

Self-review found three issues, all fixed before commit: dead code in the trace validator; two needless function-level imports; and — the substantive one — the import-boundary meta-test only exercised a helper rather than the detection logic, while the boundary checks themselves inspect packages that are still empty. The detector is now verified against synthetic violating trees, including the realistic case of an LLM import hidden inside a function body, and the vacuity is documented in the module docstring and STATUS rather than papered over.

**DECISION: KEEP.**

---

## 2026-08-30 — P2 Simulated company agent, world, and tools

**WHAT WE TRIED.** Built the monitored system: a seeded simulated world with versioned refund policies, 7 simulated tools, a trace collector, the `CompanyAgent` adapter, a minimal custom-loop agent, and 5 clean scenarios with deterministic oracles.

**WHY — and the D-004 experiment.** P2 had to settle whether Google ADK backs the MVP agent. Measured rather than assumed:

- `uv pip install --dry-run google-adk` resolves **37 new packages** and downgrades `websockets` 17.1 → 15.0.1.
- More decisively, ADK runs its own orchestration loop over LLM calls, tool dispatch, and session state — exactly the layer we must intercept for byte-identical replay (D-001). Going through it would couple the project's single most important property to a third party's internals.

The convenience ADK offers is precisely the part we need to own. **DECISION: custom loop; ADK not a dependency.** The `CompanyAgent` protocol keeps it addable later as a genuine framework-agnosticism demonstration. Recorded in D-004.

**A second finding worth recording.** Two of the five clean scenarios were initially written against *assumed* properties of the seeded world. Inspecting the generated data showed `ORD-2000` was in-window (not out), and `ORD-2005` was delivered (not pending), so `cancel_pending_order` would have exercised an error path while appearing to pass. Both were reassigned to orders that genuinely have the intended properties. Cheap to catch here; it would have quietly corrupted P3's incident ground truth.

**RESULT / EVIDENCE.** `pytest backend/tests -q` → **180 passed** in 0.54s, fully offline. All 5 clean scenarios PASS their oracles; identical seed reproduces identical trace hash and world hash across all 5. Every state mutation is traced (`test_mutations_are_all_traced` reconciles trace mutation steps against observed world deltas). Nothing outside `companyagent/` references the concrete agent class, so the adapter boundary holds.

**Honest limitation.** The agent's control flow is deterministic Python; the model narrates reasoning but does not decide. Deliberate per D-003 — a model-driven agent would make determinism harder and causal ground truth ambiguous — but it means reasoning-level failure modes cannot yet be injected. P3 injects at the tool, state, context, and policy layers instead.

**DECISION: KEEP.**

---

## Experiment log

*(Empty. First entries expected in P4 — replay determinism findings — and P7 — baseline comparison.)*

Experiments anticipated:

- P4 — whether byte-identical strict replay is achievable under LLM nondeterminism. **This is a genuine open question and may produce a negative result.**
- P5 — whether replay-effect-size ranking beats agent-confidence ranking on the seed incidents.
- P7 — AFTERMATH vs. fair single-LLM baseline on root-cause localization.
- P8 — investigator-count sweep (1 / 3 / 5 / 7): accuracy vs. latency vs. cost vs. marginal gain.
- P8 — repair tournament: does strategy diversity produce measurably better repairs than a single repair agent?
