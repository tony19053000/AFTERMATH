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

## 2026-08-30 — P3 Fault injection & incidents with ground truth

**WHAT WE TRIED.** An injection framework with hooks at the tool-result, world-state, and retry layers; an incident definition format loaded from `data/incidents/`; and 5 incidents whose ground truth is authored by the injector at injection time.

**WHY.** Trustworthy ground truth is the precondition for measuring root-cause accuracy at all (D-002). The design commitment: the injector records the trace step it perturbed, so `true_causal_step` is written by the code that did the perturbing — not inferred, not asked of a model. `true_causal_step` is deliberately **not** stored in the definition files: step ids are ordinal and only exist once a run has happened, so hand-writing one would be asserting a causal claim with no experiment behind it — the exact habit this project exists to replace.

**TWO INCIDENTS FAILED AND WERE REPLACED — this is the useful part of this entry.**

*Wrong-customer (context layer) — REMOVED as inert.* The plan was to substitute a different `customer_id` on `get_customer` so a tier change would flip refund eligibility. It fired correctly and changed nothing: `calculate_refund` re-reads the customer from world state via `order.customer_id` and never uses what `get_customer` returned. Checking further, no order in the seeded world has an age in the (30, 45] band where a tier swap could flip eligibility anyway. **A fault that cannot affect an outcome is not an incident** — shipping it would have put a guaranteed-passing case into the benchmark and inflated every rate computed over it. The `wrong_customer` kind and the context hook were deleted rather than left as dead code; `InjectionLayer.CONTEXT` remains as taxonomy, and a spec declaring it now fails loudly instead of silently reporting a false negative.

*World-state staleness — initially never fired.* `prepare_world` perturbed the environment but recorded no causal step, so the run raised rather than producing ground truth. Fixed by separating *where the perturbation happened* (before the run) from *where the wrong value entered the trace* (the first `get_policy` result). In I-005 the tool is entirely honest — it truthfully reports the only policy that exists — and the environment is what is wrong. I-001 and I-005 were kept as separate incidents precisely because they reach the same outcome by different mechanisms, which P4/P5 must be able to distinguish.

A third, smaller correction: `malformed_policy_output` originally deleted the `version` field, which raised `KeyError` inside the agent — a crash, not a traceable incident. It now serves a mislabeled version instead, so the failure surfaces on a value the agent can see.

**RESULT / EVIDENCE.** `pytest backend/tests -q` → **260 passed** in 0.63s, offline. 5 incidents across 3 injection layers, each failing its *declared* oracle (asserted, so an incident failing for an unrelated reason is caught):

| incident | layer | causal step | failing oracle | rate |
|---|---|---|---|---|
| I-001 stale policy (tool result) | tool_result | s0007 | refund_denied_outside_window | 1.00 |
| I-002 duplicate refund after retry | retry | s0019 | no_duplicate_refund | 1.00 |
| I-003 approval bypass | tool_result | s0009 | approval_required_above_limit | 1.00 |
| I-004 malformed policy version | tool_result | s0007 | refund_within_current_policy | 1.00 |
| I-005 stale policy (world state) | world_state | s0007 | refund_denied_outside_window | 1.00 |

All 5 clean scenarios still PASS with no injection recorded. Ground truth verified reproducible with **no provider at all**, so no model can have influenced it.

**Honest note on the rate.** 1.00 across the board because the agent is fully deterministic — every trial is identical. The rate is measured rather than assumed so the number stays truthful once P4 introduces resampled replay and real variance appears. It is not yet evidence of anything interesting.

**DECISION: KEEP.**

---

## 2026-08-30 — P4 Replay engine ⚠ (the highest-risk phase)

**WHAT WE TRIED.** A deterministic replay engine, counterfactual interventions, an N-trial experiment runner, and effect-size ranking. P4 existed to answer one question: **is byte-identical strict replay actually achievable?** If not, the project's premise needed rethinking.

### Experiment 1 — is strict replay byte-identical?

**Result: YES, via record/replay — and NO via live re-execution.** Both halves matter.

| configuration | byte-identical? |
|---|---|
| 5 clean scenarios, re-executed | ✅ all 5 |
| 5 incidents, fault reapplied | ✅ all 5, ground truth stable |
| mock provider (narration on) | ✅ |
| **live model, run twice, temperature 0.0** | ❌ **diverged** |
| **live model recorded, then replayed from cassette** | ✅ hash-equal, no provider instance |

The live divergence is the finding worth keeping. At `temperature=0.0`, two runs produced different narration — *"I would be happy to help you process a refund…"* vs *"I can certainly help you look into a refund…"*. **Temperature 0 is not a determinism guarantee.** The P1 record/replay machinery is what makes strict replay real, now verified against a real model rather than only the mock. Recorded as D-015.

### Experiment 2 — do counterfactuals actually discriminate?

The controls, run across all 5 incidents (5 trials each, 26 experiments total):

| incident | intervention at true cause | effect | unrelated steps tested | max effect | localized |
|---|---|---:|---:|---:|---|
| I-001 | replace_tool_result @s0007 | **+1.00** | 4 | +0.00 | ✅ s0007 |
| I-002 | skip_tool_call @s0019 | **+1.00** | 7 | +0.00 | ✅ s0019 |
| I-003 | replace_tool_result @s0009 | **+1.00** | 4 | +0.00 | ✅ s0009 |
| I-004 | replace_tool_result @s0007 | **+1.00** | 2 | +0.00 | ✅ s0007 |
| I-005 | replace_tool_result @s0007 | **+1.00** | 4 | +0.00 | ✅ s0007 |

**5/5 correct localization; perfect separation** — +1.00 at the true cause, +0.00 at every one of the 21 unrelated steps. The negative control is the load-bearing half: an engine that "fixed" everything would score identically on the positive control alone and be worthless.

**RESULT / EVIDENCE.** `pytest backend/tests -q` → **322 passed** in ~1.0s, offline.

**Two honest caveats.**

1. **The perfect separation is partly a property of the current agent.** Control flow is deterministic Python, so failure rates are 0.0 or 1.0 with no variance and effect sizes are maximally clean. Real agents will produce intermediate rates. `TrialSummary.distinct_traces` tracks trace variance so this transition is visible rather than silent, and the rates are measured rather than assumed for exactly that reason.
2. **The corrective interventions in P4's controls are written by us, not proposed by a model.** They use only the trace and a clean run — never the injector's internals — so they are genuine counterfactuals rather than a privileged undo. But whether an LLM *proposes* the right intervention unaided is untested until P5, and it is the harder problem.

**A guard became real.** `test_import_boundaries` had inspected empty stubs since P1. `replay/` is now 493 lines, and the guard was verified to fail when a model import is deliberately introduced, then restored.

**DECISION: KEEP.** The premise holds: counterfactual replay produces measurable causal evidence.

---

## Experiment log

*(Empty. First entries expected in P4 — replay determinism findings — and P7 — baseline comparison.)*

Experiments anticipated:

- P4 — whether byte-identical strict replay is achievable under LLM nondeterminism. **This is a genuine open question and may produce a negative result.**
- P5 — whether replay-effect-size ranking beats agent-confidence ranking on the seed incidents.
- P7 — AFTERMATH vs. fair single-LLM baseline on root-cause localization.
- P8 — investigator-count sweep (1 / 3 / 5 / 7): accuracy vs. latency vs. cost vs. marginal gain.
- P8 — repair tournament: does strategy diversity produce measurably better repairs than a single repair agent?
