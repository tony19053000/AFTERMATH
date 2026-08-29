# AFTERMATH — Project Requirements

**Status:** Living document. Last updated 2026-08-30 (bootstrap).
**Tagline:** *From Agent Incident to Verified Immunity.*

---

## 1. Product vision

When a tool-using AI agent fails in production, the current state of practice is an engineer reading a 400-step trajectory by hand, forming a guess, patching a prompt, and hoping. There is no experiment, no evidence, and no protection against the same failure returning three releases later.

AFTERMATH makes agent failure analysis **experimental** rather than interpretive, and makes the result **permanent** rather than disposable:

```
INCIDENT → CAUSAL INVESTIGATION → EXPERIMENTAL REPLAY → VERIFIED REPAIR → REGRESSION IMMUNITY
```

The claim we intend to defend with data: *a forensic system that runs counterfactual replay experiments localizes root causes more accurately than a capable LLM reading the same trajectory.*

## 2. Problem statement

Agentic systems fail in ways traditional software does not:

- The failure is usually **not** where the error surfaced. A wrong refund at step 40 was caused by a stale policy fetched at step 7.
- Trajectories are long, branching, and full of plausible-looking reasoning that is wrong.
- The same input can produce different behavior across runs, so "reproduce the bug" is not straightforward.
- A fix cannot be validated by re-running once — you need to know it prevents the failure *and* does not block legitimate cases.
- Nothing stops a fixed failure from silently returning after a model, prompt, or tool change.

Asking an LLM "what went wrong here?" produces a fluent, confident answer that is frequently wrong and always unfalsifiable. There is no experiment behind it.

## 3. Target users

**Primary:** engineering teams building or operating tool-using agentic systems — AI platform engineers, AI reliability engineers, backend engineers, SRE teams, agent developers, AI safety teams.

**Primary user story:** *A production agent issued a duplicate refund. I need to know which decision actually caused it, get a fix that is proven to prevent it without blocking valid refunds, and guarantee it never comes back.*

**Explicitly not the target (for now):** end consumers, non-technical product managers, general LLM chat users.

## 4. Pain points addressed

| Pain | AFTERMATH's answer |
|---|---|
| Root cause is buried in a long trajectory | Multi-perspective investigation over a structured trace |
| Diagnosis is a guess | Counterfactual replay produces measured evidence |
| Can't reproduce the failure | Deterministic, seeded replay engine |
| Don't know if the fix works | Repairs are tested, not argued for |
| Fix breaks legitimate behavior | Utility / false-positive verification on normal cases |
| Fixed bugs come back | Every verified incident becomes a permanent regression test |
| Traces contain sensitive data | Secure Forensic Vault (future; see §11) |

## 5. Core use cases

1. **Investigate an incident.** Load a failed trajectory, get a ranked set of causal hypotheses each attached to specific trace steps.
2. **Prove the cause.** Run counterfactual experiments that intervene at suspected steps and measure the change in failure rate.
3. **Repair with evidence.** Generate competing repair strategies, test them against the incident and against normal cases, and select on measurement.
4. **Acquire immunity.** Convert the verified incident into a permanent regression case in the Immunity Vault.
5. **Gate a release.** Replay a new agent version against the whole immunity suite; surface regressions before shipping.
6. **Benchmark the system.** Run AFTERMATH and the single-LLM baseline over the same incident set and compare on the primary metric.

---

## 6. MVP — NOW

The MVP is a **complete thin vertical slice**, not a partial elaborate one.

```
Simple simulated company agent
   → structured trace
   → injected known failure
   → single-LLM baseline diagnosis
   → AFTERMATH: 1 investigator → 1 counterfactual planner
   → deterministic replay experiment → evidence
   → 1 repair agent → 1 verifier
   → regression test stored in the Immunity Vault
```

**In scope for MVP:**

- Simulated customer-operations agent with ~7 simulated tools, fully deterministic simulated world (customers, orders, policies).
- Structured trace schema (JSON/JSONL) with stable step IDs.
- Fault-injection framework with recorded ground truth.
- 3–5 incidents initially, growing toward 15–20.
- Deterministic replay engine supporting step-level interventions and N-trial runs.
- Minimal AFTERMATH runtime pipeline: 1 investigator, 1 counterfactual planner, 1 repair agent, 1 verifier.
- Single-LLM baseline on the identical incident set.
- SQLite persistence of traces, experiments, verdicts, repairs, regression cases.
- FastAPI backend exposing the pipeline.
- pytest suite including determinism and regression tests.
- Metrics computed in Python from stored artifacts.

**Out of scope for MVP** (deferred, and documented as deferred): the full 16-agent swarm, TEE/attestation, the frontend, Docker, PostgreSQL, real external agent integration, CI/CD integration, live observability integrations.

## 7. Advanced version — FUTURE / OPTIONAL UPGRADE

Each of these must be justified by user value or a measured improvement, and each is a separate phase:

- **Investigator swarm:** Reasoning, Tool/API, Context & Memory, Security & Policy, State & Systems investigators (5).
- **Counterfactual planning swarm** (3) and **repair tournament** (4 strategies: minimal, reliability, security/safety, systems-level).
- **Verifier swarm** (3: regression, utility/false-positive, adversarial) + final forensic synthesizer. Target ceiling ~16 runtime agents, with adaptive escalation of up to 2 additional specialists for hard incidents.
- **Agent-count experiments:** measure 1 vs 3 vs 5 vs 7 investigators on accuracy, latency, cost, hypothesis diversity, and marginal gain. **We do not assume more agents is better — the final count is a result, not a design input.**
- Richer company agent; alternative monitored-agent frameworks; real external agent via trace-import API.
- Frontend: Incident Lab, Evidence Board, Replay Lab, Repair Tournament, Immunity Vault, (secondary) Swarm View.
- PostgreSQL, Docker, advanced replay isolation, TEE Secure Forensic Vault, CI/CD regression gating.

## 8. Non-features — what AFTERMATH is deliberately not

- Not a log viewer or observability dashboard.
- Not a generic multi-agent chat framework.
- Not an "LLM explains your trace" wrapper.
- Not an autonomous agent that patches production by itself. Repairs are proposals with evidence; a human ships them.
- Not a real-money or real-customer system. Every action in the demo is simulated.

---

## 9. Baseline (fairness is a requirement, not a courtesy)

**Baseline:** one capable LLM receives the failed trajectory and is asked for root cause, evidence, and a recommended fix. It gets **no** counterfactual replay, **no** forensic swarm, **no** experimental verification.

Fairness constraints, all mandatory:

- Identical incident set, identical trace content, identical output schema.
- Equivalent underlying model capability to what AFTERMATH's agents use.
- A competently written baseline prompt. A strawman baseline invalidates the entire result.
- Both scored by the same deterministic grader against injector ground truth.
- Baseline outputs stored as artifacts, same as AFTERMATH's.

We are measuring whether **the engineering system** helps — not whether a bigger model helps.

## 10. Evaluation

**Primary metric: correct root-cause localization rate** — fraction of incidents where the identified causal step matches the injector's `true_causal_step`.

**Secondary metrics:** correct repair rate; verified repair success; recurrence rate after repair; normal-case preservation; false-positive / false-block rate; diagnosis latency; API token cost; reproducibility (identical seed → identical result); regression detection rate; evidence-supported diagnosis rate (fraction of diagnoses backed by a replay experiment rather than assertion alone).

**Hard rule:** every number that appears in the README, UI, video, submission, or any report must be read from a stored experiment output. Inventing, estimating, or extrapolating a metric is prohibited.

## 11. Security requirements

- Secrets via `.env` only; `.env.example` carries placeholder names; `.env` is gitignored.
- No provider key ever reaches the frontend.
- All demo data synthetic; no real customer data at any point.
- The simulated agent performs no consequential external action.
- No secrets in logs or traces; trace redaction is a first-class future requirement.
- **Future — Secure Forensic Vault (TEE):** encrypted incident ingestion, secrets detection, PII redaction/tokenization, trace normalization, evidence hashing and integrity, trusted replay, remote attestation where feasible. **This is explicitly post-MVP and must never block the core pipeline. Nothing may claim to run in a TEE until it does.**

## 12. Hackathon requirements

- Reproducible from a clean clone: documented setup, seeded runs, stored artifacts.
- A demonstrable end-to-end story on real execution, not a mock-up.
- An improvement history (`docs/CHANGELOG.md`) recording what was tried, why, the result, and the keep/modify/remove decision — **including failed experiments**.
- Honest reporting of limitations.

## 13. Success criteria

**MVP is successful when:** an incident with known ground truth runs end-to-end and produces a correctly localized root cause supported by a replay experiment, a repair that measurably prevents the incident without breaking normal cases, and a stored regression test that fails against the unrepaired agent and passes against the repaired one — reproducibly, from stored artifacts.

**The project is successful when:** the above holds across a 15–20 incident benchmark, AFTERMATH measurably outperforms a fair single-LLM baseline on root-cause localization, and the agent-count question is answered with data.

## 14. Assumptions

- Incidents are synthetic and injected, so ground truth is controlled and trustworthy.
- The monitored agent's trajectory can be captured as a structured, replayable trace.
- Enough of the agent's behavior is deterministic-under-seed that counterfactual replay is meaningful; nondeterministic model calls are handled by record/replay.
- Initial LLM access is via Gemini API; the abstraction makes this swappable.
- A single developer plus Claude Code sub-agents is the whole team; scope must stay proportionate.

## 15. Known limitations (to be stated honestly, not hidden)

- Synthetic incidents are not production incidents. Results indicate mechanism viability, not production accuracy.
- Replay fidelity is bounded by how faithfully the simulated world models reality.
- Counterfactual evidence establishes *causal relevance under the simulation*, not proof of real-world causation.
- Benchmark size (15–20) is small; report confidence honestly and avoid over-claiming.
- LLM nondeterminism is mitigated, not eliminated.

## 16. Future roadmap

Ordered by dependency, not ambition: vertical slice → immunity vault → fair baseline + benchmark → swarm expansion with agent-count experiments → frontend → hardening/reproducibility → TEE vault → external integrations (trace-import API, CI/CD gating, observability). See `docs/PHASES.md`.
