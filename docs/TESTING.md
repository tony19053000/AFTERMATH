# AFTERMATH — Testing Strategy

**Status:** strategy defined; no suite exists yet (arrives in P1).

---

## 1. Philosophy

AFTERMATH is a system that produces *evidence*. If our own evidence-producing machinery is not itself verified, the product's central claim collapses. Testing here is not hygiene — it is the thing being sold.

Three principles:

1. **The deterministic core must be provably deterministic.** Same trace, same seed, same result — asserted, not assumed. This is the single most important test class in the project.
2. **Tests must not depend on a live LLM.** The default suite runs offline against the mock provider or recorded calls. Live-provider tests are marked `@pytest.mark.live` and excluded by default.
3. **Controls matter as much as cases.** Every claim about causal detection needs a negative control. An engine that reports "yes, causal" for every step is worse than useless, and only a negative control catches it.

**Never weaken, skip, or delete a test to obtain a green run.** A failing test that reflects a real defect is a successful outcome.

---

## 2. Layers

### Unit tests
Trace schema validation and round-tripping · content hashing stability · each simulated tool in isolation · world-state transitions · intervention spec construction · effect-size math · grader matching logic · metric computation · persistence repositories.

### Integration tests
Scenario run → complete valid trace · injection → reproducible failure · replay of a stored trace → identical outcome · full forensic pipeline on the mock provider · repair evaluation → prevention and false-block rates · immunity case generation → suite run.

### Runtime-agent tests
Every agent's output validates against its Pydantic schema · malformed model output is handled without crashing the pipeline · agents never receive ground truth (asserted) · prompt files load and render · **ranking depends on effect size, not confidence** — feed the ranker a high-confidence wrong hypothesis and a low-confidence right one; the right one must win.

### Replay tests — the critical class
- **Strict replay is byte-identical.** Replaying an unmodified trace reproduces the original outcome exactly.
- **Failure-rate stability.** N-trial replay of an incident reproduces its failure rate within documented tolerance.
- **Positive control.** Intervening at the injector's `true_causal_step` materially reduces the failure rate.
- **Negative control.** Intervening at an unrelated step does *not* reduce it.
- **State restoration.** Branching from step *k* restores exactly the world state recorded at *k*.
- **Purity.** `replay/` performs zero LLM calls — asserted by import inspection.

### Benchmark tests
Grader correctness including near-miss and adjacent-step cases · baseline and AFTERMATH provably receive an identical incident set · metrics recomputed from stored artifacts match reported values exactly · benchmark run is reproducible.

### Regression / immunity tests
A generated regression case **fails against the unrepaired agent** and **passes against the repaired one** · the full suite runs against an arbitrary agent version · a deliberately reintroduced bug is detected.

### Security tests
No secret appears in any trace, log, or artifact (scanned) · `.env` is gitignored and no key is committed (history scanned) · prompt-injection incident is handled without policy bypass · no provider key is reachable from the frontend · simulated tools perform no real external action.

### Architecture tests
Import-boundary enforcement: `replay/`, `immunity/`, `benchmark/` (excluding the baseline module) import nothing from `llm/` · no vendor SDK is imported outside `llm/` and `companyagent/` · layering direction is respected.

### Frontend tests (P9)
Components render from real API fixtures · no mocked or hard-coded data path exists in the production build · a "running" indicator maps to a real backend job state · end-to-end run through the UI.

---

## 3. Commands

Real as of P1. Note: `python3 -m venv` is broken on this machine (missing `ensurepip`), so `uv` is used for environment setup.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e "backend[dev]"

.venv/bin/python -m pytest backend/tests -q       # default: offline, deterministic
.venv/bin/python -m pytest backend/tests -m live  # opt-in, requires GEMINI_API_KEY
.venv/bin/python -m pytest --cov=aftermath backend/tests
```

Markers: `slow` · `live` · `replay` · `benchmark` · `security`. `addopts` excludes `live` by default, so the suite never needs a network or a key.

**Current:** 64 passed, ~0.45s.

---

## 4. Test data policy

All fixtures synthetic. No real customer data, ever. Secrets in fixtures are obvious placeholders (`test-key-not-real`). Recorded LLM calls are committed as fixtures **after** being scanned for secrets. Traces used in tests are small and hand-checkable where possible.

---

## 5. Acceptance-criteria mapping

Each phase's acceptance criteria in `docs/PHASES.md` map to named tests. A phase is not done until every criterion has a test that demonstrates it. When closing a phase, record the real `pytest` summary line in `docs/CONTEXT.md` — not a paraphrase, not "tests pass".

| Phase | Criterion | Test |
|---|---|---|
| P1 | trace round-trips with identical hash | `test_trace_roundtrip_hash_stable` |
| P1 | recorded provider call replays without network | `test_recording_replay_offline` |
| P1 | deterministic layers import no LLM | `test_import_boundaries` |
| P2 | same seed → same world | `test_world_determinism` |
| P2 | no untraced state mutation | `test_trace_completeness` |
| P3 | incident reproduces at stable rate | `test_incident_reproducibility` |
| P3 | ground truth has no LLM provenance | `test_ground_truth_is_injector_authored` |
| P4 | strict replay byte-identical | `test_strict_replay_identical` |
| P4 | positive control | `test_intervention_at_true_cause_reduces_failure` |
| P4 | negative control | `test_intervention_at_unrelated_step_no_effect` |
| P5 | ranking follows evidence, not confidence | `test_ranking_prefers_effect_size` |
| P6 | regression case fails unrepaired, passes repaired | `test_immunity_case_controls` |
| P7 | identical incident set for both systems | `test_baseline_parity` |
| P7 | reported metrics match artifacts | `test_metrics_match_artifacts` |
| P8 | agent count is configuration | `test_swarm_configurable` |

Extend this table as phases land.
