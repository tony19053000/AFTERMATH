# CLAUDE.md — Permanent Operating Manual for AFTERMATH

This file is the standing instruction set for every Claude Code session working in this repository. It contains permanent rules, not session state. Session state lives in `docs/CONTEXT.md` and `docs/STATUS.md`.

---

## 1. Read before significant work

Before any non-trivial change, read in this order:

1. `docs/PROJECT_REQUIREMENTS.md` — what we are building and why
2. `docs/ARCHITECTURE.md` — how it is built
3. `docs/PHASES.md` — the plan and the current phase's definition of done
4. `docs/STATUS.md` — where the project actually stands
5. `docs/CONTEXT.md` — what the last session did, what is broken, what is next
6. `docs/DECISIONS.md` — decisions already made; do not silently reverse them
7. `docs/TESTING.md` — how correctness is established here

**The repository is the source of truth. Never rely on conversation memory.** If a document contradicts the code, that is a bug in the document — fix it in the same work cycle.

For a trivial change (typo, comment, single-line doc edit), reading `STATUS.md` and `CONTEXT.md` is enough.

---

## 2. What AFTERMATH is

AFTERMATH turns an Agentic-AI failure into verified immunity:

```
INCIDENT → CAUSAL INVESTIGATION → EXPERIMENTAL REPLAY → VERIFIED REPAIR → REGRESSION IMMUNITY
```

It is **not** a log summarizer, an observability dashboard, a multi-agent chat toy, or an LLM that guesses root causes.

**The founding engineering principle:**

> **AGENTS THINK. PYTHON TESTS.**

LLM agents may investigate, hypothesize, design experiments, propose repairs, interpret, and critique. Deterministic Python — and only deterministic Python — may establish replay outcomes, scoring, ground-truth comparison, regression execution, arithmetic, state restoration, test assertions, metrics, and benchmark numbers.

**An LLM must never become the authoritative source for anything deterministic code can establish.** If you catch yourself asking a model to decide whether an experiment passed, stop: that is a Python assertion.

---

## 3. Permanent project principles

1. **Working before sophisticated.** A complete, thin, working vertical slice beats a partial elaborate one. Always.
2. **Evidence over consensus.** Agent agreement generates hypotheses; replay produces evidence. Never resolve a causal question by majority vote among LLMs.
3. **Never fake anything.** No invented metrics, no simulated "agent runs" that did not run, no claimed TEE execution, no fabricated attestation, no placeholder benchmark numbers in README/UI/demo. Every number shown anywhere must trace to a stored experiment artifact on disk. A stub must be labeled a stub.
4. **UI reflects real backend state.** If a node shows "running", a real backend task is running. No decorative animation standing in for work.
5. **Ground truth comes from the injector, not from a model.** Incidents are synthetic precisely so we control the true cause.
6. **Baseline fairness is non-negotiable.** The single-LLM baseline gets the same incidents and equivalent model capability. We are measuring the *system*, not model size. Never handicap the baseline.
7. **Replaceable technology ≠ changeable purpose.** Gemini, Google ADK, SQLite, and the simple company agent are initial, swappable choices. The purpose, evaluation methodology, and core concept are not.

---

## 4. Architecture constraints

- **Provider abstraction is mandatory.** Business logic never imports a vendor SDK directly. All model calls go through the `llm` provider interface. All monitored-agent interaction goes through the company-agent adapter interface.
- **The monitored agent is a plug-in, not a dependency.** Nothing in the forensics pipeline may assume Google ADK, or even that the agent is in-process. It consumes traces.
- **Determinism is a property we defend.** The replay engine, tool layer, and simulated world must be seedable and reproducible. Anything nondeterministic (a live model call) is recorded and replayed from the record, never re-sampled during scoring.
- **Layer direction:** `api → orchestration → (forensics | replay | immunity) → core/persistence`. Lower layers never import higher ones. `core` imports nothing from the project except itself.
- **Keep deterministic logic free of LLM calls.** `replay/` and `immunity/` contain no model calls at all, and neither does `benchmark/` apart from the single `benchmark/baseline.py` module (which *is* an LLM by definition). The grader, metrics, and runner in `benchmark/` are strictly deterministic. This is enforced by an import-boundary test.

---

## 5. Coding standards

- Python 3.12, `from __future__ import annotations`, type hints on all public functions.
- Pydantic models for every schema crossing a boundary (API, trace, persistence, agent I/O).
- Small focused modules. If a file passes ~400 lines, it probably wants splitting.
- Explicit interfaces (`Protocol` / ABC) at every swap point.
- Structured logging (`structlog`-style key-value or stdlib `logging` with `extra=`). Never log secrets, never log full customer records.
- Real error handling. No bare `except:`. No silently swallowed exceptions.
- No magic values — constants and enums.
- Docstrings where the *why* is not obvious; skip them where the signature says everything.
- Clear over clever. No premature abstraction, no premature microservices.

**Dependencies:** before adding a major one, (1) state the problem it solves, (2) check whether something already installed solves it, (3) weigh maintenance and portability, (4) record it in `docs/DECISIONS.md`. Popularity is not a reason.

---

## 6. Testing rules

- `pytest`. Tests live in `backend/tests/`, mirroring the package layout.
- Every phase ships tests. A feature without tests is not done.
- **No live LLM calls in the default test run.** Use recorded fixtures or the mock provider. Live-provider tests are marked and opt-in.
- Determinism tests are first-class: replaying the same trace with the same seed must produce byte-identical outcomes.
- Tests must not be weakened, skipped, or deleted to obtain a green run.
- Full detail in `docs/TESTING.md`.

---

## 7. Development workflow

```
IMPLEMENT → TEST → REVIEW → FIX → RETEST → DOCUMENT
```

A feature is complete only when **all** hold:

- acceptance criteria in `docs/PHASES.md` are satisfied,
- relevant tests pass (paste the real summary line),
- no blocking (CRITICAL/HIGH) review issue remains,
- previously working behavior still works,
- documentation reflects reality.

Code existing is not completion.

The four development sub-agents (`project-manager`, `coder`, `tester`, `reviewer`) are configured in `.claude/agents/` and described in `.claude/AGENTS.md`. **They are Claude Code development agents. They are entirely unrelated to the AFTERMATH runtime agents documented in `docs/PRODUCT_AGENTS.md`.** Never conflate the two.

---

## 8. Documentation update requirements

After any substantial work cycle, update:

| If… | Update |
|---|---|
| always | `docs/STATUS.md`, `docs/CONTEXT.md` |
| architecture changed | `docs/ARCHITECTURE.md` |
| requirements changed | `docs/PROJECT_REQUIREMENTS.md` |
| a significant decision was made | `docs/DECISIONS.md` |
| an experiment was run (success **or** failure) | `docs/CHANGELOG.md` |
| test strategy changed | `docs/TESTING.md` |
| runtime-agent design changed | `docs/PRODUCT_AGENTS.md` |
| public behavior changed | `README.md` |

Outdated architecture diagrams are treated as defects.

---

## 9. Anti-drift rules

Do not silently change: the project objective, the core AFTERMATH concept, the evaluation methodology, architecture boundaries, major technologies, the target user, or the primary metric (correct root-cause localization rate).

If a change genuinely seems necessary: explain why → record the proposal in `docs/DECISIONS.md` → preserve compatibility where reasonable → update architecture/requirements docs. Then proceed.

Scope discipline: implement the current phase. Adjacent good ideas get noted in `docs/STATUS.md` under next/backlog, not built inline.

---

## 10. Security rules

- **Never commit** API keys, passwords, tokens, credentials, or real customer data. `.env` is gitignored; `.env.example` holds placeholder names only.
- Never log secrets. Never expose provider keys to the frontend — the browser talks only to our backend.
- All demo data is synthetic.
- The simulated company agent performs **no real consequential actions**: no payments, no real emails, no external writes. Refunds, cancellations, and approvals mutate an in-memory/SQLite simulated world only.
- Do not build a real external integration unless the requirements explicitly call for it and it is safe.
- Never claim TEE execution, confidential computing, or attestation unless it is genuinely happening.

---

## 11. Git rules

- Conventional commits: `feat:` `fix:` `test:` `docs:` `refactor:` `chore:`.
- A phase is committed only after its Definition of Done in `docs/PHASES.md` is fully met.
- Never force push. Never rewrite or destroy remote history. Never overwrite unrelated remote work.
- Inspect repository state before pushing.
- Do not push a broken phase because time is short.
- Remote status is tracked in `docs/STATUS.md`.

---

## 12. Context persistence rule

The end of a work cycle is not the last line of code — it is the `STATUS.md` / `CONTEXT.md` update. Write `CONTEXT.md` as if the next session has read nothing and remembers nothing, because it has and it does.
