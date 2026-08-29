# AFTERMATH — Decision Log

Architectural and product decisions, with reasoning, so future sessions do not repeatedly re-litigate settled questions. Append; do not rewrite history. If a decision is reversed, add a new entry that supersedes the old one and mark the old one.

Format: **ID · Date · Decision · Alternatives · Reason · Consequences · Reversible?**

---

## D-001 · 2026-08-30 · Deterministic replay is the evidence mechanism; LLMs never adjudicate outcomes

**Decision.** Causal claims are established by a deterministic Python replay engine measuring failure-rate change under intervention. LLM agents may hypothesize, plan, propose, and critique — never decide whether an experiment passed.

**Alternatives considered.** (a) LLM-as-judge over the trace; (b) multi-agent majority vote on root cause; (c) statistical correlation over historical traces.

**Reason.** (a) and (b) are unfalsifiable — fluent, confident, frequently wrong, and impossible to verify. This is precisely the failure mode of every "AI explains your logs" product. Counterfactual intervention gives a measurable effect size. It is also the project's only genuinely defensible differentiator.

**Consequences.** Replay fidelity becomes the highest-risk engineering problem (P4). Nondeterministic model calls need record/replay. `replay/`, `immunity/`, and `benchmark/` must contain no LLM calls, enforced by test.

**Reversible?** No. This is the project's identity. Reversing it produces a different product.

---

## D-002 · 2026-08-30 · Synthetic, injected incidents as the benchmark

**Decision.** The incident set is synthetic, produced by a controlled fault injector that records ground truth (`true_causal_step`, `injected_failure`) at injection time.

**Alternatives considered.** (a) Real production incident traces; (b) LLM-generated incidents with LLM-labeled causes; (c) public agent-failure datasets.

**Reason.** We need trustworthy ground truth to measure root-cause accuracy at all. (a) is unavailable and unlabeled. (b) is circular — using a model to grade a model's diagnosis. (c) lacks replayable execution state.

**Consequences.** Results demonstrate mechanism viability, not production accuracy — this limitation must be stated honestly. Benchmark size is small (15–20), so claims stay proportionate. **Ground truth must never come from a model.**

**Reversible?** Yes — real traces can be added later as an additional evaluation set.

---

## D-003 · 2026-08-30 · Start with a deliberately simple simulated company agent

**Decision.** The monitored agent is a simple simulated customer-operations agent with ~7 simulated tools and a seeded simulated world.

**Alternatives considered.** (a) A sophisticated multi-agent company system up front; (b) integrating a real external agent immediately.

**Reason.** The interesting engineering is in the forensic and replay layers, not in the monitored agent. A complex agent early would make determinism harder, failure injection murkier, and root-cause ground truth ambiguous — undermining the thing we are actually trying to measure. Simplicity here is a research control, not laziness.

**Consequences.** Early demos are modest. Sophistication is a later phase. The `CompanyAgent` adapter boundary makes upgrading cheap.

**Reversible?** Yes, by design — the adapter exists for exactly this.

---

## D-004 · 2026-08-30 · Minimal custom agent loop for the MVP company agent — **RESOLVED in P2**

**Decision.** The MVP company agent is a minimal custom loop implemented behind the `CompanyAgent` protocol. Google ADK is **not** a dependency. An ADK adapter may be added later as a demonstration of framework-agnosticism.

**Alternatives considered.** (a) Minimal custom agent loop; (b) Google ADK; (c) OpenAI Agents SDK; (d) LangGraph.

**Reason.** Two findings, measured during P2 rather than assumed:

1. **Determinism control (decisive).** D-001 requires intercepting every nondeterministic call so replay can serve it from a record. ADK runs its own orchestration loop over LLM calls, tool dispatch, and session state. Achieving byte-identical strict replay through it would mean coupling to ADK internals — taking on framework-version risk in the single most important property the project has. A custom loop makes every nondeterministic call pass through our own `LLMProvider`, which already records and replays (verified in P1).
2. **Dependency weight.** `uv pip install --dry-run google-adk` resolves **37 new packages** and downgrades `websockets` (17.1 → 15.0.1). That is a large surface for a component whose deliberate purpose (D-003) is to be a simple, controllable trace producer.

The convenience ADK offers — orchestration, tool registration, session handling — is exactly the part we need to control ourselves. It solves a problem we do not have while complicating the one we do.

**Consequences.** No ADK dependency. The `CompanyAgent` protocol still isolates the choice, so an ADK-backed agent can be added under `companyagent/adk.py` without touching the forensics pipeline — and doing so would be a genuine demonstration that AFTERMATH is framework-agnostic. Documentation referring to ADK as the initial framework is updated to reflect this.

**Reversible?** Yes — that is the entire purpose of the adapter. This decision changes the initial implementation, not the architecture.

---

## D-005 · 2026-08-30 · SQLite first, behind a repository layer

**Decision.** SQLite for persistence, accessed through a thin repository layer; large payloads stored as hashed files under `data/artifacts/`.

**Alternatives considered.** (a) PostgreSQL from day one; (b) flat files only; (c) a document store.

**Reason.** Zero operational overhead, no service to run, trivially reproducible from a clean clone — which matters for hackathon reproducibility. Flat files alone would make querying experiments painful. The repository layer is the migration seam.

**Consequences.** Concurrency limits will eventually matter; PostgreSQL migration is a future phase touching only `persistence/`.

**Reversible?** Yes, cheaply.

---

## D-006 · 2026-08-30 · Gemini initially, behind an `LLMProvider` abstraction

**Decision.** Gemini API as the initial provider; all model access through `llm/base.py`; a mock provider and a record/replay wrapper ship in P1.

**Alternatives considered.** (a) Direct vendor SDK calls throughout; (b) a heavy framework such as LangChain; (c) multi-provider from the start.

**Reason.** (a) creates vendor lock-in in business logic. (b) adds a large dependency and indirection we do not need. (c) is premature. The abstraction costs one file and buys swap-ability plus deterministic testing.

**Consequences.** No vendor SDK import outside `llm/`. Swapping providers touches one file. The mock provider makes the default test run offline and deterministic.

**Reversible?** Yes.

---

## D-007 · 2026-08-30 · A fair, competently-prompted single-LLM baseline

**Decision.** The baseline is one capable LLM given the same trace, the same output schema, a genuinely well-written prompt, and equivalent model capability — graded by the identical deterministic grader.

**Alternatives considered.** (a) No baseline; (b) a weak/strawman baseline; (c) comparison against a published system.

**Reason.** Without a baseline the project proves nothing. With a strawman baseline it proves nothing *and* is dishonest — and a reviewer will spot it immediately. The claim under test is "the engineering system helps", which requires holding model capability constant.

**Consequences.** Effort must go into making the baseline good. **The result is reported honestly even if AFTERMATH loses.** The baseline prompt gets an explicit fairness review recorded here in P7.

**Reversible?** No — this is a methodology commitment.

---

## D-008 · 2026-08-30 · Runtime agent count is an experimental result, not a design input

**Decision.** Start with 4 runtime agents (investigator, counterfactual planner, repair, verifier). Expand only where a measured sweep (1/3/5/7 investigators, etc.) shows marginal improvement justifying the cost.

**Alternatives considered.** (a) Build the full 16-agent swarm immediately; (b) fix the count by intuition.

**Reason.** "More agents = better" is an assumption, and it is exactly the kind of assumption this project exists to test. Building 16 agents before the pipeline works also risks having none of them demonstrably useful. Cost and latency scale with agent count and must be weighed against accuracy.

**Consequences.** P8 runs configuration sweeps. Agent count is configuration, never hard-coded. **If more agents do not help, that finding is reported as a result, not buried.**

**Reversible?** Yes — the count is configuration.

---

## D-009 · 2026-08-30 · TEE / Secure Forensic Vault is post-MVP and optional

**Decision.** TEE work is P11, unweighted, and may not block or delay the core pipeline. The trust boundary is kept architecturally clean now (distinct ingestion step, hashed artifacts) so it can be inserted later.

**Alternatives considered.** (a) TEE from the start; (b) drop it entirely; (c) *claim* TEE without implementing it.

**Reason.** TEE addresses a real problem (traces carry PII, credentials, proprietary content) but is worthless without a working forensic pipeline underneath. (c) is fraud and is prohibited outright.

**Consequences.** **No TEE, attestation, or confidential-computing claim may appear in the README, UI, video, or submission until real attestation output exists.** If unimplemented, it is described as future work, explicitly.

**Reversible?** Yes — scope, not architecture.

---

## D-010 · 2026-08-30 · Backend evidence pipeline before frontend

**Decision.** The frontend is P9, after the benchmark produces real numbers.

**Alternatives considered.** (a) UI-first for demo appeal; (b) parallel development.

**Reason.** A UI built before the evidence pipeline would necessarily display mock data, and mock data has a way of surviving into the demo. The project's stated standard is that every displayed value comes from a stored artifact; the only reliable way to honor that is to have artifacts first.

**Consequences.** No visual progress for several phases. The demo risk is accepted deliberately. When built, the UI reads only real backend state — including "running" indicators.

**Reversible?** Yes, but reversing it re-introduces exactly the fake-demo risk we are avoiding.

---

## D-011 · 2026-08-30 · Weighted, criteria-derived completion tracking

**Decision.** `docs/STATUS.md` completion = Σ(phase weight × phase % done), where phase % done = satisfied acceptance criteria ÷ total criteria.

**Alternatives considered.** (a) Intuitive percentage; (b) task counting; (c) no tracking.

**Reason.** An arbitrary percentage is noise. Deriving it from acceptance criteria means the number means something and cannot drift optimistically.

**Consequences.** Every phase needs enumerable acceptance criteria (they have them). Weights are revisited only with an entry here.

**Reversible?** Yes.


---

## D-012 · 2026-08-30 · Pin `gemini-3.1-pro-preview` for both agents and baseline

**Decision.** `DEFAULT_MODEL = "gemini-3.1-pro-preview"`, used by both AFTERMATH's forensic agents (`agent_model`) and the single-LLM baseline (`baseline_model`).

**Alternatives considered.** (a) `gemini-2.5-pro` — the value originally configured; (b) the `gemini-pro-latest` alias; (c) a flash-tier model for cost.

**Reason.** Checked against the API rather than assumed:

- **`gemini-2.5-pro` returns HTTP 404 on this key.** It was our configured default in `config.py` and `.env.example` from P1 onward and would have failed at P5 — mid-pipeline, with no obvious cause. Caught by listing the models endpoint before use.
- **The alias was rejected for reproducibility.** `gemini-pro-latest` resolves to whatever is current; a stored benchmark result produced under an alias cannot be re-derived later once the alias moves. Pinning an explicit name is what makes §10's "every number traces to a stored artifact" hold over time.
- Flash tier was rejected for the primary comparison: the baseline must have genuinely capable reasoning or the comparison is unfair by construction (D-007). Flash remains available for cost-sensitive sweeps in P8, recorded if used.

Both sides are set to the same model deliberately. **If they ever diverge, the benchmark stops measuring the engineering system and starts measuring the model gap** — a test asserts they match by default.

**Consequences.** A preview model can be withdrawn or changed by the provider. Two mitigations already in place: every call is recorded to a cassette, so any completed run replays offline byte-identically regardless of upstream changes; and a `live`-marked test asserts the pinned model is still reachable, so a disappearance surfaces as a clear failure rather than a confusing one. Revisit when a stable `gemini-3.x-pro` ships.

**Reversible?** Yes — one constant in `config.py`.

---

## D-013 · 2026-08-30 · The test suite is hermetic against local configuration

**Decision.** An autouse fixture isolates every test from the repository `.env` and from `GEMINI_API_KEY`. Tests marked `live` opt out and are excluded from the default run.

**Alternatives considered.** (a) Leave `Settings` reading `.env` in tests; (b) require developers not to keep a `.env`; (c) hermetic by default with an explicit opt-out.

**Reason.** Adding a real key immediately broke three tests — not because the code was wrong, but because `Settings` read the developer's local `.env` and the suite's assertions changed with it. Two problems, one of them serious: a suite whose result depends on an untracked file is not a suite; and worse, a stray key on any machine could silently turn tests documented as "offline and deterministic" into live, billed network calls. The project's testing philosophy says the default run must be offline and reproducible, so that has to be enforced rather than assumed.

**Consequences.** `pytest backend/tests` passes identically with or without a `.env`, and with or without the key exported — both verified. Live coverage is a deliberate `-m live` run.

**Reversible?** Yes, but reversing it re-introduces exactly the leak described above.


---

## D-014 · 2026-08-30 · "Replay" means deterministic re-execution, not playback

**Decision.** The replay engine re-executes a run from fixed inputs — same scenario, same world seed, same fault, same recorded model responses — rather than stepping through a recorded trace re-emitting recorded values.

**Alternatives considered.** (a) Playback: walk the stored trace and replay each recorded value; (b) deterministic re-execution; (c) process-level snapshot/restore.

**Reason.** Playback cannot answer a counterfactual. After an intervention the run *must* be free to diverge — that divergence is the measurement. A playback engine would faithfully reproduce the original trace and learn nothing. (c) is far heavier than the problem requires while the monitored agent is in-process.

**Consequences.** Replay fidelity depends on the run being deterministic given its inputs, which is why every nondeterministic call goes through the recording provider (D-006) and why the world uses an integer `day` rather than a clock. The word "replay" is used in this specific sense throughout the codebase and docs; it is stated in the engine's module docstring so no reader assumes playback semantics.

**Reversible?** Yes, but playback would remove the ability to run counterfactuals, which is the product.

---

## D-015 · 2026-08-30 · Strict replay requires recorded model responses — measured, not assumed

**Decision.** Byte-identical strict replay is achieved by serving model calls from a cassette. Re-executing against a live model is **not** treated as reproducible, and the engine's strict mode never calls one.

**Alternatives considered.** (a) Assume `temperature=0` is deterministic enough; (b) require recorded responses; (c) abandon byte-identical replay and compare outcomes only.

**Reason.** Measured directly, because P4 flagged this as the risk that could invalidate the project. Running incident I-001 twice against a live model at `temperature=0.0`:

- **Not byte-identical.** Reasoning text diverged on the first narration step — "I would be happy to help you process a refund…" vs "I can certainly help you look into a refund…".
- Recording that same run and replaying it from the cassette with **no provider instance at all** was byte-identical, hash-equal.

So (a) is false: temperature 0 is not a determinism guarantee. The record/replay machinery built in P1 is what makes strict replay real, and it is now verified against a real model rather than only the mock.

**Consequences.** Any experiment intended to be reproducible must run under a recorded or mock provider. A benchmark run's cassettes are part of its evidence, not an optimization. A `live`-marked test documents the divergence so the finding is not lost.

**Important caveat, recorded honestly.** In these runs the *outcome* was identical across live executions even though the text was not — but only because this agent's control flow is deterministic Python and narration cannot change a decision (D-003). **That stability is a property of the current simple agent, not of the replay engine.** When the monitored agent becomes model-driven, live divergence will be able to change outcomes, and the failure rate will become a genuine statistic rather than 0.0/1.0. `TrialSummary.distinct_traces` already tracks this so the shift will be visible rather than silent.

**Reversible?** No — this is a measured property of the environment, not a preference.
