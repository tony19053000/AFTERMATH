# AFTERMATH — Testing Strategy

**Status:** live as of P2. 180 tests, fully offline and deterministic.

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

**Current:** 322 passed offline (~1.0s), plus 3 `live` tests that pass against the real provider (~10s) when run deliberately.

**Hermeticity.** An autouse fixture isolates tests from the repository `.env` and from `GEMINI_API_KEY` (D-013). The default run behaves identically whether or not a key is present on the machine — verified both ways. `live`-marked tests opt out and are the only ones permitted to reach a network.

---

## 4. Test data policy

All fixtures synthetic. No real customer data, ever. Secrets in fixtures are obvious placeholders (`test-key-not-real`). Recorded LLM calls are committed as fixtures **after** being scanned for secrets. Traces used in tests are small and hand-checkable where possible.

---

## 5. Acceptance-criteria mapping

Each phase's acceptance criteria in `docs/PHASES.md` map to named tests. A phase is not done until every criterion has a test that demonstrates it. When closing a phase, record the real `pytest` summary line in `docs/CONTEXT.md` — not a paraphrase, not "tests pass".

| Phase | Criterion | Test |
|---|---|---|
| P1 | trace round-trips with identical hash | `test_roundtrip_preserves_content_and_hash` |
| P1 | mock provider is deterministic | `test_same_request_same_response` |
| P1 | recorded provider call replays without network | `test_replay_is_byte_identical_and_offline` |
| P1 | replay miss refuses to go live | `test_replay_miss_raises_rather_than_going_live` |
| P1 | schema creates; trace persists and reloads | `test_save_then_load_returns_identical_trace` |
| P1 | `/health` returns 200 | `test_health_returns_ok` |
| P1 | deterministic layers import no LLM | `test_deterministic_layers_do_not_import_llm` |
| P1 | the boundary detector actually detects | `TestDetectorActuallyDetects` |
| P2 | same seed → same world | `test_same_seed_produces_identical_world` |
| P2 | same seed → same trace | `test_same_seed_produces_identical_trace` |
| P2 | valid trace from a scenario run | `test_trace_is_valid_and_round_trips` |
| P2 | no untraced state mutation | `test_mutations_are_all_traced` |
| P2 | clean scenarios pass their oracles | `TestCleanScenariosPassTheirOracles::test_scenario_passes` |
| P2 | agent swap touches only companyagent/ | `test_an_alternative_agent_implementation_is_accepted` |
| P2 | oracles catch real failures (negative control) | `TestOracleIndependence` |
| P3 | incident reproduces at stable rate | `test_failure_rate_is_stable_and_documented` |
| P3 | incident fails its *declared* oracle | `test_incident_fails_its_declared_oracle` |
| P3 | ground truth has no LLM provenance | `test_injector_module_makes_no_llm_call` |
| P3 | agent never sees ground truth | `test_agent_never_receives_the_ground_truth` |
| P3 | clean runs still pass | `TestCleanRunsStillPass::test_clean_scenario_passes` |
| P3 | injected vs clean differential | `test_injected_and_clean_runs_of_the_same_scenario_differ` |
| P3 | definitions validate from disk | `test_every_definition_file_parses` |
| P3 | a fault that never fires raises | `test_an_injection_that_never_fires_raises` |
| P4 | strict replay byte-identical | `test_clean_run_replays_byte_identically`, `test_incident_replays_byte_identically` |
| P4 | failure rate reproduced | `test_baseline_failure_rate_matches_the_incident` |
| P4 | positive control | `test_positive_control_intervening_at_the_true_cause_prevents_failure` |
| P4 | negative control | `test_negative_control_unrelated_steps_have_no_effect` |
| P4 | localization picks the true cause | `test_localization_picks_the_true_causal_step` |
| P4 | ranking ignores confidence | `test_ranking_ignores_confidence` |
| P4 | experiments re-runnable from artifacts | `test_artifact_round_trips_and_is_rerunnable` |
| P4 | no model in the evidence path | `TestNoModelInTheEvidencePath` |
| P5 | ranking follows evidence, not confidence | `test_ranking_prefers_effect_size` |
| P6 | regression case fails unrepaired, passes repaired | `test_immunity_case_controls` |
| P7 | identical incident set for both systems | `test_baseline_parity` |
| P7 | reported metrics match artifacts | `test_metrics_match_artifacts` |
| P8 | agent count is configuration | `test_swarm_configurable` |

Extend this table as phases land.
