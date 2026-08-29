# AFTERMATH — Session Context & Handoff

**Purpose:** if the session ends or context resets, this file alone (plus the docs it points to) must be enough to continue accurately. Written for a reader who remembers nothing.

**Last updated:** 2026-08-30 — end of bootstrap cycle.
**Current phase:** P0 complete (committed `c6825fb`) → next is **P1 Foundations**.

---

## What was completed this cycle

Project bootstrap only. No application code was written, by design.

- `git init` on branch `main` in an otherwise empty workspace (no prior history existed).
- `CLAUDE.md` — the permanent operating manual.
- `docs/PROJECT_REQUIREMENTS.md`, `docs/ARCHITECTURE.md`, `docs/PHASES.md`, `docs/STATUS.md`, `docs/CONTEXT.md`, `docs/DECISIONS.md`, `docs/PRODUCT_AGENTS.md`, `docs/TESTING.md`, `docs/CHANGELOG.md`.
- `README.md`, `.gitignore`, `.env.example`.
- 11 phases designed (P0–P10 weighted, P11 optional/unweighted), each with acceptance criteria and tests.

## What currently works

Nothing executable. This is a documentation-only state — correct for end of P0.

## What is broken

Nothing.

## What was tested

Nothing. No test suite exists yet; it arrives in P1.

## Current state of the repository

```
CLAUDE.md  README.md  .gitignore  .env.example
.claude/agents/{project-manager,coder,tester,reviewer}.md   # dev agents — do NOT reconfigure
docs/{PROJECT_REQUIREMENTS,ARCHITECTURE,PHASES,STATUS,CONTEXT,DECISIONS,PRODUCT_AGENTS,TESTING,CHANGELOG}.md
```

No `backend/`, no `frontend/`, no `data/` yet — P1 and P2 create them.

## Important commands

None yet. P1 establishes: `pip install -e backend[dev]`, `pytest backend/tests`, `uvicorn aftermath.api.app:app --reload`. Update this section as they become real.

## Important files to read before working

`CLAUDE.md` first, then `docs/PHASES.md` (current phase's acceptance criteria), `docs/STATUS.md`, `docs/DECISIONS.md`. Read `docs/ARCHITECTURE.md` before touching structure.

## Active assumptions

- Python 3.12.3, Node 22.22.1, git 2.43 available locally (verified).
- Gemini API key not yet supplied — P1 proceeds on the mock provider.
- No GitHub remote yet — local commits only.
- Google ADK vs. a custom agent loop is **not yet decided**; see DECISIONS D-004. The adapter boundary means this can be settled in P2 without disruption.

## Next recommended task

Start **P1.1**: create the `backend/` package scaffold, `pyproject.toml`, `config.py`, and the pytest harness. Acceptance criteria are in `docs/PHASES.md` under P1.

## Unresolved questions (need the project owner)

1. GitHub repository URL — needed to configure a remote.
2. Gemini API key placement in `.env` — needed before any live-model run.
3. Hackathon deadline and any required tech constraints — affects how far past P7 we scope.
4. Google ADK for the MVP company agent, or a minimal custom loop? (See D-004; a custom loop is the lower-risk default for determinism.)

## Warnings / traps for the next session

- **Do not reconfigure the Claude Code development agents.** `.claude/` is already set up and is out of scope for project work. Those four agents are *development* agents; the AFTERMATH runtime agents in `docs/PRODUCT_AGENTS.md` are a completely different thing.
- **Do not let an LLM decide an experimental outcome.** Replay results, scoring, and metrics are Python. This is the project's core principle, and it is the easiest one to violate accidentally.
- **Do not build the frontend or the 16-agent swarm early.** Both are sequenced after the evidence pipeline works, deliberately.
- **P4 (replay engine) is the highest-risk phase.** If byte-identical strict replay turns out to be impossible, stop and record it in DECISIONS + CHANGELOG rather than working around it quietly.
- **No invented numbers.** Nothing may quote a benchmark result until P7 writes real artifacts.
- **Ground truth comes from the fault injector, never from a model.**
