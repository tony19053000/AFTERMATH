# AFTERMATH

**From Agent Incident to Verified Immunity.**

> ⚠️ **Project status: bootstrap (P0 of 11).** Documentation and development plan are in place; implementation has not started. There are no benchmark results yet, and this README will not carry any number that does not come from a stored experiment artifact.

---

## The problem

When a tool-using AI agent fails in production, an engineer reads a 400-step trajectory by hand, forms a guess, patches a prompt, and hopes. The failure is usually not where the error surfaced — a wrong refund at step 40 was caused by a stale policy fetched at step 7. There is no experiment behind the diagnosis, no proof the fix works, no check that it doesn't block legitimate cases, and nothing stopping the same bug from returning three releases later.

Asking an LLM "what went wrong here?" returns a fluent, confident answer that is frequently wrong and always unfalsifiable.

## The approach

```
INCIDENT → CAUSAL INVESTIGATION → EXPERIMENTAL REPLAY → VERIFIED REPAIR → REGRESSION IMMUNITY
```

AFTERMATH treats agent failure analysis as an experiment rather than an interpretation:

1. Capture the failed trajectory as a structured, replayable trace.
2. Investigator agents propose causal hypotheses bound to specific trace steps.
3. Counterfactual agents design experiments that could disprove them.
4. **A deterministic replay engine runs those experiments** — intervene at step 7, replay 20 times, measure the change in failure rate.
5. The cause is the one with the measured effect, not the one with the best explanation.
6. Competing repairs are generated, then **tested** — against the incident and against normal cases, so a fix that works by blocking everything loses.
7. The verified incident becomes a permanent regression test. It cannot silently come back.

**The founding principle:**

> **AGENTS THINK. PYTHON TESTS.**

LLMs hypothesize, design experiments, propose repairs, and critique. Deterministic Python establishes every outcome, score, and metric. No model is ever the authority on something code can measure.

### What that looks like

```
Original trajectory        →  18/20 failures
Intervene at step 7        →   0/20 failures     ← evidence
Intervene at step 14       →  12/20 failures
Intervene at step 21       →  18/20 failures     ← negative control
```

That is a measurement, not an opinion. It is the difference between AFTERMATH and an LLM log summarizer.

## What AFTERMATH is not

Not a log summarizer. Not an observability dashboard. Not a multi-agent chat framework. Not an LLM that guesses root causes. Not an autonomous agent that patches production by itself — repairs are proposals with evidence attached, and a human ships them.

## Planned capabilities

| | |
|---|---|
| **Incident Lab** | Run scenarios against a monitored agent and watch a controlled failure occur |
| **Evidence Board** | Hypotheses pinned to real trace steps, strengthened or weakened by experiment |
| **Replay Lab** | Counterfactual branches with measured failure rates |
| **Repair Tournament** | Competing repair strategies compared on test evidence |
| **Immunity Vault** | Verified incidents as permanent regression cases; release gating for new agent versions |
| **Secure Forensic Vault** | *Future, optional.* Confidential handling of sensitive traces |

## Architecture (planned)

Python · FastAPI · deterministic replay engine · SQLite · pytest · React/Next.js frontend · Gemini API and Google ADK as **initial, swappable** choices behind adapters. The monitored agent, the LLM provider, and the database are all replaceable by design — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Evaluation (planned)

Primary metric: **correct root-cause localization rate** against ground truth recorded by the fault injector — never by a model.

Compared against a **fair baseline**: one capable LLM, the same incidents, an equivalent model, a competently written prompt, no replay and no swarm. The question is whether the *engineering system* helps, not whether a bigger model helps. Results will be reported honestly, including if AFTERMATH loses.

## Quick start

Not yet available — implementation begins in P1. Setup instructions land with the backend scaffold.

## Documentation

| | |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Permanent operating manual for this repository |
| [docs/PROJECT_REQUIREMENTS.md](docs/PROJECT_REQUIREMENTS.md) | Product requirements, MVP vs. future scope |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, trace schema, data flow |
| [docs/PHASES.md](docs/PHASES.md) | 11-phase plan with acceptance criteria |
| [docs/STATUS.md](docs/STATUS.md) | Live status and completion tracking |
| [docs/CONTEXT.md](docs/CONTEXT.md) | Session handoff notes |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decision log with reasoning |
| [docs/PRODUCT_AGENTS.md](docs/PRODUCT_AGENTS.md) | AFTERMATH's runtime agent design |
| [docs/TESTING.md](docs/TESTING.md) | Testing strategy |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Experiment history, including failures |

## Honesty commitments

Stated up front, because they constrain everything above:

- Every number in this README, the UI, and any demo comes from a stored experiment artifact.
- No claim of TEE execution, attestation, or confidential computing until it genuinely runs.
- Incidents are synthetic; results demonstrate mechanism viability, not production accuracy.
- Failed experiments are recorded in the changelog alongside successful ones.
- All demo data is synthetic. The simulated agent performs no real-world action.
