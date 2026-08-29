# AFTERMATH — Session Context & Handoff

**Purpose:** if the session ends or context resets, this file alone (plus the docs it points to) must be enough to continue accurately. Written for a reader who remembers nothing.

**Last updated:** 2026-08-30 — end of P1.
**Current phase:** P1 complete → next is **P2 Simulated company agent, world, and tools**.

---

## What was completed this cycle

**P1 Foundations.** The skeleton every later phase stands on.

- `backend/` package (`aftermath`), `pyproject.toml` (hatchling, Python ≥3.12), pytest config with markers.
- `config.py` — env-driven `Settings` (`AFTERMATH_` prefix, reads root `.env`). No secret in code.
- `core/hashing.py` — canonical JSON + `sha256:` content hashing.
- `core/trace.py` — the trace schema: 8 discriminated step types, frozen models, ordinal `step_id`, parent-chain validation, `world_snapshot_ref`, nondeterminism records, JSONL round-trip with hash verification.
- `llm/` — `LLMProvider` protocol, deterministic `MockProvider`, `GeminiProvider` (deferred SDK import), `RecordingProvider` (record/replay cassettes), `factory.build_provider`.
- `persistence/` — SQLite schema (10 tables), `ArtifactStore` (immutable, content-addressed), `TraceRepository`.
- `api/app.py` — FastAPI skeleton with `/health` only.
- `tests/` — 64 tests including the import-boundary architecture guard.

## What currently works

- `pytest backend/tests -q` → **64 passed** in ~0.45s, fully offline.
- `uvicorn aftermath.api.app:app` boots; `GET /health` → `200 {"status":"ok","llm_provider":"mock","deterministic_provider":true}` (verified against a real server, not just TestClient).
- Traces round-trip model → JSONL → model with identical content hash; tampering is detected on load.
- Recorded LLM calls replay byte-identically with no provider instance at all.

## What is broken

Nothing known.

## What was tested

All 6 P1 acceptance criteria, each with a named test:

| Criterion | Test |
|---|---|
| Trace round-trips with identical hash | `test_roundtrip_preserves_content_and_hash` |
| Mock provider deterministic | `test_same_request_same_response`, `test_independent_instances_agree` |
| Recorded call replays byte-identically, offline | `test_replay_is_byte_identical_and_offline` |
| SQLite schema creates; trace persists and reloads | `test_schema_creates_and_stamps_version`, `test_save_then_load_returns_identical_trace` |
| `/health` returns 200 | `test_health_returns_ok` |
| Deterministic layers import no LLM | `test_deterministic_layers_do_not_import_llm` + `TestDetectorActuallyDetects` |

Also covered: evidence-tampering detection (trace and artifact), replay-miss refusing to go live, ground-truth provenance, immutability, malformed input.

## Important commands

```bash
# Environment (system python3-venv lacks ensurepip; uv is installed and used instead)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e "backend[dev]"

.venv/bin/python -m pytest backend/tests -q          # 64 passed, offline
.venv/bin/python -m pytest backend/tests -m live     # opt-in, needs GEMINI_API_KEY
.venv/bin/python -m uvicorn aftermath.api.app:app --port 8000
```

## Important files

`backend/aftermath/core/trace.py` is the most load-bearing file in the project — step ids, hashing, and the JSONL format are what P4's replay verification and P5's hypothesis addressing depend on. `backend/tests/arch/test_import_boundaries.py` enforces the AGENTS THINK / PYTHON TESTS principle statically.

## Active assumptions

- Python 3.12.3, Node 22.22.1, git 2.43, `uv` available locally (verified).
- `python3 -m venv` is broken on this machine (no `ensurepip`); use `uv venv`.
- Gemini API key not yet supplied — P2–P4 run entirely on the mock provider.
- GitHub remote configured: `origin` → https://github.com/tony19053000/AFTERMATH.git; `main` tracks `origin/main`.
- D-004 (Google ADK vs. custom agent loop) is still **open** and must be resolved in P2.

## Next recommended task

**P2.1** — the seeded simulated world (customers, orders, versioned policies, refund ledger). Acceptance criteria are in `docs/PHASES.md` under P2. Note that P2 forces the D-004 decision: evaluate whether Google ADK permits the record/replay hooks deterministic replay needs, and if it does not, use a minimal custom loop and keep an ADK adapter as the framework-agnosticism demonstration. Record the outcome in `docs/DECISIONS.md`.

## Unresolved questions (need the project owner)

1. ~~GitHub repository URL~~ — resolved 2026-08-30.
2. Gemini API key placement in `.env` — needed before P5's live run.
3. Hackathon deadline and any required tech constraints — affects how far past P7 we scope.
4. Google ADK for the MVP company agent, or a minimal custom loop? (D-004; decide during P2. A custom loop is the lower-risk default for determinism.)

## Warnings / traps for the next session

- **Do not reconfigure the Claude Code development agents.** `.claude/` is already set up. Those four are *development* agents; the AFTERMATH runtime agents in `docs/PRODUCT_AGENTS.md` are a completely different thing.
- **Do not let an LLM decide an experimental outcome.** Replay results, scoring, and metrics are Python. `tests/arch/test_import_boundaries.py` enforces this — if it starts failing, that is the alarm working, not a test to relax.
- The boundary test currently inspects **empty** package stubs, so it passes with nothing to check. It becomes load-bearing in P4. Do not mistake its green for proof that P4's engine is clean.
- **P4 (replay engine) is the highest-risk phase.** If byte-identical strict replay proves impossible, record it in DECISIONS + CHANGELOG rather than working around it quietly.
- **No invented numbers.** Nothing may quote a benchmark result until P7 writes real artifacts.
- **Ground truth comes from the fault injector, never from a model.**
- Traces are frozen Pydantic models — mutate via `model_copy(update=...)`, and expect `content_hash()` to change when semantic content does.
