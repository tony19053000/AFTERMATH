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

## D-004 · 2026-08-30 · Google ADK is an initial convenience, behind an adapter — **OPEN**

**Decision (provisional).** Google ADK may back the first company-agent implementation, but only behind the `CompanyAgent` protocol. **The final call is deferred to P2.**

**Alternatives considered.** (a) Minimal custom agent loop; (b) Google ADK; (c) OpenAI Agents SDK; (d) LangGraph.

**Reason.** ADK is convenient and aligned with the initial Gemini choice. However, deterministic replay (D-001) requires precise control over every nondeterministic call, and a framework's internal orchestration can obstruct that. A minimal custom loop is the lower-risk default for determinism.

**Consequences.** P2 must evaluate whether ADK permits the required record/replay hooks. If it does not, use a custom loop and keep an ADK adapter as a demonstration of framework-agnosticism. **Resolve and update this entry during P2.**

**Reversible?** Yes — that is the entire purpose of the adapter.

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
