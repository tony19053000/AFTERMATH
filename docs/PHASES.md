# AFTERMATH — Development Phases

Designed for **vertical slices**: every phase after P1 leaves a system that runs end to end and proves something. Ordering is driven by dependency and risk, not by feature attractiveness.

**Risk note:** the two highest-risk components are the **replay engine** (P4) and **determinism under LLM nondeterminism** (P1/P4). They are scheduled early and deliberately, because if deterministic counterfactual replay does not work, the entire premise of the project needs rethinking — and we want to learn that in week one, not week four.

**Weights** are used to compute overall completion in `docs/STATUS.md`. They reflect effort × risk, and sum to 100.

| Phase | Name | Weight | Depends on |
|---|---|---:|---|
| P0 | Bootstrap & documentation system | 4 | — |
| P1 | Foundations: schema, config, providers, persistence, test harness | 10 | P0 |
| P2 | Simulated company agent + deterministic world & tools | 10 | P1 |
| P3 | Fault injection + first incidents with ground truth | 8 | P2 |
| P4 | Deterministic replay engine + counterfactual interventions | 14 | P3 |
| P5 | Minimal AFTERMATH forensic pipeline (the vertical slice) | 14 | P4 |
| P6 | Immunity Vault: verified incident → permanent regression test | 8 | P5 |
| P7 | Fair baseline + benchmark harness + real metrics | 10 | P5, P6 |
| P8 | Swarm expansion + agent-count experiments (data-driven) | 10 | P7 |
| P9 | Frontend: Incident Lab, Evidence Board, Replay Lab, Tournament, Vault | 8 | P7 |
| P10 | Hardening, reproducibility, Docker, demo | 4 | P9 |
| P11 | *(Optional)* TEE Secure Forensic Vault | 0† | P10 |

† P11 is stretch scope and carries no weight; it cannot affect completion percentage or block anything.

---

## P0 — Bootstrap & documentation system

**Objective.** Establish the persistent development system so future sessions continue without context loss.
**Scope.** Git init; `CLAUDE.md`; all `docs/`; `.gitignore`; `.env.example`; architecture, phases, testing strategy, status tracking, context handoff. No application code.
**Acceptance criteria.** All documents exist and are mutually consistent; phases have acceptance criteria; STATUS has a derived (not arbitrary) percentage; a fresh session can orient from the repo alone.
**Tests.** None (documentation phase).
**Deliverable.** Bootstrapped repository + initial commit.
**DoD.** Self-review for contradictions passed; committed.

## P1 — Foundations

**Objective.** The skeleton every later phase stands on.
**Scope.** `backend/` package + `pyproject.toml`; `config.py` (env-driven settings, no secrets in code); `core/` trace schema as Pydantic models (envelope, all step types, stable `step_id`, `world_snapshot_ref`, nondeterminism records) + content hashing; `llm/` provider protocol with `mock` and `gemini` implementations plus the record/replay wrapper; `persistence/` SQLite repositories + migrations; artifact store; pytest harness with fixtures; FastAPI app skeleton with `/health`.
**Likely files.** `backend/aftermath/{config,core/trace,core/hashing,llm/base,llm/mock,llm/gemini,llm/recording,persistence/*,api/app}.py`, `backend/tests/`.
**Acceptance criteria.** Trace round-trips model → JSONL → model with identical content hash; mock provider is deterministic; a recorded Gemini call replays byte-identically without network; SQLite schema creates and a trace persists and reloads; `/health` returns 200; **an architecture test asserts `replay/`, `immunity/`, and `benchmark/` (excluding `benchmark/baseline.py`) import no LLM modules** (directories present even if near-empty).
**Tests.** Schema round-trip, hash stability, provider record/replay, persistence CRUD, import-boundary test.
**Deliverable.** Installable backend package, green `pytest`.
**DoD.** Standard (see §DoD below).

## P2 — Simulated company agent, world, and tools

**Objective.** A monitored agent that produces real traces — simple, deterministic, and replaceable.
**Scope.** Seeded simulated world (customers, orders, policies with versions, refund ledger); tools `get_customer`, `get_order`, `get_policy`, `calculate_refund`, `request_human_approval`, `issue_simulated_refund`, `cancel_order` — pure over world state, **no real side effects**; the `CompanyAgent` protocol and its first implementation (**resolved in D-004: minimal custom loop, no ADK dependency**); trace emission hooks on every reasoning step, tool call, result, and state mutation; 3–5 clean scenarios with correctness/safety oracles.
**Acceptance criteria.** Running a scenario with a fixed seed produces a valid trace; the same seed reproduces the same world state and tool results; every tool call and state mutation appears in the trace with a stable ID; clean scenarios pass their oracles; swapping the agent implementation requires touching only `companyagent/`.
**Tests.** World determinism, per-tool unit tests, trace completeness (no untraced mutation), oracle correctness on clean runs, adapter-boundary test.
**Deliverable.** `POST /scenarios/{id}/run` → a real trace.

## P3 — Fault injection & incidents with ground truth

**Objective.** Reproducible failures whose true cause we control.
**Scope.** Injection framework (hooks at tool-result, world-state, context, and policy layers); incident definition format carrying `incident_id`, `description`, `expected_behavior`, `observed_behavior`, `injected_failure`, `true_causal_step`, `expected_safe_behavior`, `severity`, `replay_configuration`; **first 3–5 incidents** — start with stale policy retrieval, duplicate refund after retry, and human-approval bypass; a set of normal (non-failing) cases for later false-positive measurement.
**Acceptance criteria.** Each incident reproduces its failure under its seed at a stable, documented rate; ground truth is written by the injector and **never** by a model; clean runs of the same scenarios still pass; incidents load from `data/incidents/` and validate against the schema.
**Tests.** Reproducibility per incident, ground-truth schema validation, clean-vs-injected differential, a test asserting ground truth has no LLM provenance.
**Deliverable.** An incident library with trustworthy ground truth.

## P4 — Deterministic replay engine + counterfactual interventions ⚠ highest risk

**Objective.** Turn "I think step 7 caused it" into a measurement. This is the heart of the product.
**Scope.** Replay from a trace with world-state restoration; strict mode (nondeterministic calls served from the record) and resampled mode; `InterventionSpec` (replace tool result, alter world state, modify context, drop/reorder step, force policy or approval outcome); N-trial experiment runner; deterministic outcome scoring against scenario oracles; effect-size computation and hypothesis ranking; experiment artifacts persisted.
**Acceptance criteria.** Strict replay of an unmodified trace reproduces the original outcome **byte-identically**; N-trial replay of an incident reproduces its failure rate within a documented tolerance; intervening at the known `true_causal_step` measurably reduces the failure rate; intervening at an unrelated step does not; **zero LLM calls occur inside `replay/` — enforced by test**; experiments are persisted and re-runnable from artifacts.
**Tests.** Byte-identical strict replay; failure-rate stability; positive control (true cause → large effect); negative control (irrelevant step → no effect); no-LLM-import test; artifact re-run test.
**Deliverable.** `POST /experiments` producing real counterfactual evidence.
**Risk note.** If byte-identical strict replay proves impossible, stop and record the finding in DECISIONS + CHANGELOG before adapting the approach. Do not paper over it.

## P5 — Minimal AFTERMATH forensic pipeline (the vertical slice)

**Objective.** The complete story, end to end, with the *fewest* runtime agents that prove it.
**Scope.** Forensic orchestrator; **1** investigator (hypotheses bound to step IDs); **1** counterfactual planner (hypothesis → executable `InterventionSpec`); **1** repair agent; **1** verifier; a synthesizer report assembled from evidence; agent I/O as strict Pydantic schemas; full pipeline persisted and exposed via API.
**Acceptance criteria.** For each seed incident, the pipeline runs end to end and produces a report where the top-ranked cause is chosen by **replay effect size, not agent confidence**; the report cites concrete experiment artifacts for every causal claim; a proposed repair is tested against the incident and against normal cases; the whole run is reproducible from stored artifacts; no LLM output is treated as an experimental result anywhere.
**Tests.** Pipeline integration test with the mock provider; agent I/O schema validation; a test asserting ranking depends on effect size (feed it a high-confidence wrong hypothesis and a low-confidence right one — the right one must win); repair evaluation correctness.
**Deliverable.** **The MVP.** Incident → evidenced cause → tested repair.

## P6 — Immunity Vault

**Objective.** Make a fixed failure permanently unable to return.
**Scope.** Convert a verified incident into a regression case (scenario + seed + injection + oracle + expected safe behavior); vault storage; suite runner against any agent version; release-gate report (`17 protected / 1 regression → RELEASE WARNING`).
**Acceptance criteria.** A generated regression case **fails against the unrepaired agent and passes against the repaired one** — both asserted in Python; the suite runs against an arbitrary agent version and reports per-case status; a deliberately reintroduced bug is caught by the suite.
**Tests.** Case generation, negative control (unrepaired agent must fail), positive control (repaired agent must pass), suite runner, reintroduced-regression detection.
**Deliverable.** `POST /immunity/run` with a real release gate.

## P7 — Fair baseline + benchmark harness + real metrics

**Objective.** Find out whether AFTERMATH actually works better — honestly.
**Scope.** Single-LLM baseline (same trace, same output schema, **competently written prompt**, equivalent model capability, no replay/swarm/verification); deterministic grader comparing diagnoses to injector ground truth; expand the incident set toward **15–20**; metrics computation over stored artifacts (primary: root-cause localization rate; plus repair correctness, recurrence, normal-case preservation, false-block rate, latency, token cost, reproducibility, evidence-supported diagnosis rate); benchmark run artifacts and a report.
**Acceptance criteria.** Baseline and AFTERMATH receive an identical incident set and are graded by the identical grader; every reported number is read from a stored artifact — **no number is computed by an LLM or by hand**; results are reproducible from a clean run; the baseline prompt is reviewed for fairness and the review is recorded in DECISIONS; results are reported honestly **even if AFTERMATH loses**.
**Tests.** Grader unit tests (including near-miss and adjacent-step cases), identical-input-set assertion, metric computation tests, end-to-end benchmark smoke test.
**Deliverable.** A defensible benchmark result with real numbers.

## P8 — Swarm expansion + agent-count experiments

**Objective.** Scale the runtime swarm **only where measurement justifies it**.
**Scope.** Add the 5 specialized investigators, 3 counterfactual planners, 4 repair strategies (minimal / reliability / security / systems) as a repair tournament, 3 verifiers (regression / utility / adversarial), and the final synthesizer; adaptive escalation (≤2 extra specialists on hard incidents); **configuration-sweep experiments over 1, 3, 5, 7 investigators** measuring root-cause accuracy, latency, token cost, useful-hypothesis diversity, and marginal gain.
**Acceptance criteria.** Runtime agent count is configuration, not hard-coded; each sweep configuration runs the same benchmark and stores artifacts; the chosen production configuration is justified by measured marginal improvement and recorded in DECISIONS + CHANGELOG; **if more agents do not help, that is the finding and it is reported as such**; cost and latency are reported alongside accuracy.
**Tests.** Configuration-driven swarm assembly, per-agent-role I/O tests, sweep harness reproducibility, tournament selection correctness (best repair wins on evidence, not on argument).
**Deliverable.** A data-driven answer to "how many agents?".

## P9 — Frontend

**Objective.** Make the evidence legible. Visual identity: aircraft black box × forensic evidence board × replay lab × CI/CD safety system — not a glowing-orb AI dashboard.
**Scope.** Incident Lab (run scenarios, watch a controlled failure occur); Evidence Board (real trace steps, hypotheses pinned to steps, evidence strengthening/weakening them); Replay Lab (counterfactual branches with real failure rates); Repair Tournament (candidates compared on test evidence); Immunity Vault (suite + release gate). Agent Swarm View is **secondary** and built last.
**Acceptance criteria.** Every displayed value comes from a backend API reading stored artifacts — **no hard-coded or mocked data anywhere in the UI**; any "running" indicator maps to a real backend job state; the UI is usable without it; no provider key reaches the browser.
**Tests.** Component tests on real API fixtures, an end-to-end run through the UI, a check that no fixture/mock data path exists in production build.
**Deliverable.** A demo that shows real evidence.

## P10 — Hardening, reproducibility, demo

**Objective.** Clean-clone reproducibility and an honest submission.
**Scope.** Docker/compose; setup docs verified from scratch; secrets scan across history; structured logging review; error-path hardening; security tests (prompt-injection incident, secrets-in-trace redaction); README with real benchmark numbers; demo script; limitations stated plainly.
**Acceptance criteria.** A clean clone reproduces the benchmark to documented tolerance; no secret exists anywhere in history; README numbers match stored artifacts exactly; limitations documented.
**Tests.** Clean-environment reproduction, secrets scan, security tests, full suite green.
**Deliverable.** Hackathon-ready, portfolio-ready repository.

## P11 — *(Optional)* TEE Secure Forensic Vault

**Objective.** Confidential forensics on sensitive traces.
**Scope.** Encrypted ingestion, secrets detection, PII redaction/tokenization, normalization, evidence hashing and integrity chain, trusted replay, remote attestation where feasible.
**Acceptance criteria.** Redaction and secrets detection demonstrably work on planted samples; the evidence integrity chain verifies; **any TEE or attestation claim is backed by real attestation output — otherwise the feature is labeled "not implemented" and no such claim is made anywhere.**
**Deliverable.** Genuine confidential-forensics capability, or an honest statement that it is future work.

---

## Definition of Done (applies to every phase)

- [ ] Implementation complete
- [ ] Acceptance criteria satisfied and demonstrated
- [ ] Unit + integration tests pass (real summary line recorded)
- [ ] Previously passing tests still pass
- [ ] No blocking (CRITICAL/HIGH) review issue remains
- [ ] `docs/STATUS.md` updated (completion recomputed from weights)
- [ ] `docs/CONTEXT.md` updated for handoff
- [ ] `docs/CHANGELOG.md` updated where an experiment was run
- [ ] `docs/ARCHITECTURE.md` updated if architecture changed
- [ ] `docs/PRODUCT_AGENTS.md` updated if runtime agents changed
- [ ] `README.md` updated if public behavior changed
- [ ] Git commit created (conventional message)
- [ ] Pushed if a remote is configured
