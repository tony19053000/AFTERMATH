# AFTERMATH

**From Agent Incident to Verified Immunity.**

> **Project status: P7 of 11 complete (78%).** The full loop runs — incident → evidenced cause → tested repair → permanent regression case — and it has now been benchmarked against a fair single-LLM baseline.
>
> Root cause correctly localized in **5/5 seed incidents**, both on the deterministic path and against live agents (where **5/5 hypotheses were agent-proposed**, not fallback). Repairs are measured on prevention *and* on whether they break legitimate cases; 4/5 incidents get an accepted repair, and the fifth is reported as having none rather than being given a bad one. 386 tests, all offline.
>
> The baseline initially **beat** AFTERMATH's agent pipeline (0.90 vs 0.75). One measured fix closed the gap to a **tie**. AFTERMATH's *deterministic* configuration scores **0.95** and beats the baseline. All three numbers are published below. 848 tests, all offline.

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

Real output from incident I-001 (a superseded refund policy served at step s0007). Each step is replaced with the value it would carry in a healthy run, 5 trials each:

```
Original trajectory                          →  5/5 failures
Correct s0007  get_policy                    →  0/5 failures    effect +1.00  ← the injected fault
Correct s0009  calculate_refund              →  0/5 failures    effect +1.00  ← downstream of it
Correct s0003  get_order                     →  5/5 failures    effect  0.00
Correct s0005  get_customer                  →  5/5 failures    effect  0.00
Correct s0012  issue_simulated_refund        →  5/5 failures    effect  0.00
```

That is a measurement, not an opinion — and it shows the method's real shape. Three steps are ruled out by evidence. Two tie at the top, because the stale policy **causes** the wrong refund calculation, so correcting either one prevents the failure. **Effect size localizes the causal chain, not the single root cause.** Picking s0007 from that pair currently relies on an earliest-step tie-break, which is a heuristic rather than evidence — and separating cause from consequence is exactly what the forensic agents in P5 have to earn.

## What AFTERMATH is not

Not a log summarizer. Not an observability dashboard. Not a multi-agent chat framework. Not an LLM that guesses root causes. Not an autonomous agent that patches production by itself — repairs are proposals with evidence attached, and a human ships them.

## Planned capabilities

| | |
|---|---|
| **Incident Lab** | Run scenarios against a monitored agent and watch a controlled failure occur |
| **Evidence Board** | Hypotheses pinned to real trace steps, strengthened or weakened by experiment |
| **Replay Lab** | Counterfactual branches with measured failure rates |
| **Repair Tournament** | Competing repair strategies compared on test evidence |
| **Immunity Vault** | ✅ Built. Verified incidents as permanent regression cases; release gating for new agent versions |
| **Secure Forensic Vault** | *Future, optional.* Confidential handling of sensitive traces |

## Architecture (planned)

Python · FastAPI · deterministic replay engine · SQLite · pytest · React/Next.js frontend · Gemini API as the **initial, swappable** model provider behind an adapter. The monitored agent is a minimal custom loop rather than an agent framework — deterministic replay requires controlling every nondeterministic call, and a framework's own orchestration sits exactly where that control is needed ([D-004](docs/DECISIONS.md)). The monitored agent, the LLM provider, and the database are all replaceable by design — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Benchmark results

20 synthetic incidents, `gemini-3.7-flash`, identical incident set and identical deterministic grader for both systems. Primary metric: **exact root-cause localization** against ground truth recorded by the fault injector, never by a model. A near miss is reported but never counted as a success.

| configuration | localization | exact | wrong | abstained |
|---|---:|---:|---:|---:|
| AFTERMATH — deterministic counterfactual sweep | **0.95** | 19 | 0 | 1 |
| AFTERMATH — LLM agents + sweep fallback | **0.90** | 18 | 1 | 1 |
| Baseline — one capable LLM, no replay | **0.90** | 18 | 2 | 0 |
| AFTERMATH — LLM agents alone *(superseded)* | 0.75 | 15 | 1 | 4 |

**What this says, plainly:**

1. **Counterfactual replay beats a capable LLM** — 0.95 vs 0.90, on the same incidents with the same grader.
2. **The LLM agent layer has not yet earned its place.** Alone it scored 0.75, *worse* than the baseline, because it proposes 1–2 hypotheses and abstains when they miss. A fallback to the exhaustive sweep lifted it to 0.90 — a tie with the baseline, still below the deterministic engine it sits on top of.
3. AFTERMATH is wrong less often than the baseline (1 vs 2) and abstains rather than guessing. **The metric does not penalize guessing**, which structurally favours a system that always answers. That is a property of the metric as much as of the systems, and is noted rather than used as an excuse.

**Both grading conventions**, because they disagree about who leads. Three of the wrong answers across both systems name the `tool_call` step instead of the `tool_result` step *of the same call* — a labelling difference, not a different diagnosis:

| convention | AFTERMATH | Baseline |
|---|---:|---:|
| strict — result step only | **0.90** | **0.90** |
| lenient — either step of the correct call | 0.95 | **1.00** |

Picking one would be choosing a headline, so both are given.

Every number above is read from `data/results/` — including the superseded 0.75 run, retained because the before/after *is* the evidence that the fix worked. The fairness review of the baseline prompt is [D-017](docs/DECISIONS.md); the reasoning for not tuning the guard library after seeing results is [D-019](docs/DECISIONS.md).

**Limits.** 20 synthetic incidents: one answer moves a rate by 5 points, so a 3-incident gap is suggestive, not conclusive. Results demonstrate mechanism viability, not production accuracy.

## Quick start

The backend runs fully offline on a deterministic mock provider — no API key needed.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e "backend[dev]"

.venv/bin/python -m pytest backend/tests -q                 # 848 passed
.venv/bin/python -m uvicorn aftermath.api.app:app --port 8000
curl -s localhost:8000/health
```

Run the full forensic pipeline on a seed incident — no API key needed, the
deterministic path uses no model at all:

```python
from aftermath.forensics.orchestrator import ForensicOrchestrator
from aftermath.injection.incidents import load_incidents

report = ForensicOrchestrator(None, trials=3).investigate(load_incidents()["I-001"])
print(report.root_cause_step)   # s0007, chosen by measured effect
print(report.resolution)        # how it was decided: measurement or heuristic
print(report.repair)            # prevention_rate, false_block_rate, accepted
```

Run the immunity suite as a release gate:

```python
from aftermath.immunity.vault import ImmunityVault
from aftermath.immunity.runner import AgentVersion, run_suite

vault = ImmunityVault()
print(run_suite(vault.load_all(), AgentVersion.unrepaired()).summary())
# 0/4 protected, 4 regression(s) -> RELEASE WARNING

print(run_suite(vault.load_all(), AgentVersion("v2.0", vault.repairs_of_record())).summary())
# 4/4 protected, 0 regression(s) -> RELEASE OK
```

Run a monitored scenario and inspect the trace it produces:

```python
from aftermath.companyagent.world import build_world
from aftermath.companyagent.scenarios import get_scenario
from aftermath.companyagent.simple import SimpleCustomerOpsAgent
from aftermath.llm.mock import MockProvider

run = SimpleCustomerOpsAgent(MockProvider()).run(
    get_scenario("refund_in_window"), build_world(seed=1337)
)
print(run.trace.outcome)        # judged by a deterministic oracle, not a model
print(run.trace.content_hash()) # identical on every re-run with the same seed
```

`uv` is used rather than `venv` because this project's dev machine lacks `ensurepip`; plain `pip install -e "backend[dev]"` works too.

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
