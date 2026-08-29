# Development Sub-Agent Team

Four project-level Claude Code sub-agents, defined in `.claude/agents/`. These are **development** agents that build this repository. If the product itself contains AI agents, those are **product/runtime** agents and are entirely separate.

| Agent | File | Role | Writes code? |
|---|---|---|---|
| `project-manager` | [project-manager.md](agents/project-manager.md) | Coordinator: understands requirements, plans, delegates, verifies, integrates, documents, owns git | No (only trivial edits) |
| `coder` | [coder.md](agents/coder.md) | Implementation: production code, APIs, schemas, integrations, bug fixes | Yes |
| `tester` | [tester.md](agents/tester.md) | Independent QA: runs/writes tests, edge and failure cases, regressions, acceptance verification | Test files only |
| `reviewer` | [reviewer.md](agents/reviewer.md) | Adversarial senior review: logic, security, privacy, architecture drift, fake functionality | No — read-only by tool config |

## Invocation

```
Agent(subagent_type: "project-manager", prompt: "...")
```

For any multi-step work, invoke `project-manager` and let it delegate. Invoke `coder`, `tester`, or `reviewer` directly only for a single narrow task.

## Default cycle

```
MANAGER  reads docs + status, defines ONE clear task
   ↓
CODER    implements
   ↓
TESTER   runs/writes tests  ──fail──▶ CODER fixes ──▶ TESTER retests
   ↓
REVIEWER independently reviews  ──CRITICAL/HIGH──▶ CODER fixes ──▶ TESTER retests
   ↓
MANAGER  checks acceptance criteria → marks complete
```

Fix cycles are capped: if an issue survives two coder→tester rounds, the manager re-scopes rather than looping.

## Delegation depth

| Task | Chain |
|---|---|
| Typo / tiny doc change | Manager handles directly |
| Simple implementation | coder → tester |
| Important implementation | coder → tester → reviewer |
| Architecture-sensitive / risky | coder → tester → reviewer → coder → tester |

## Task format

Every substantial delegated task specifies: OBJECTIVE, RELEVANT FILES, CONSTRAINTS, ACCEPTANCE CRITERIA, TEST EXPECTATIONS, EXPECTED OUTPUT.

## Standing rules

- **Context** — repository documentation is the source of truth, not chat history. The manager names the exact files each agent must read; never dump the repo into a sub-agent.
- **Concurrency** — never two agents editing the same source file. Coder owns implementation, tester owns tests, reviewer writes nothing. Parallelize only genuinely independent tasks.
- **Boundaries** — the coder never verifies its own work; the reviewer never becomes the implementer; the tester never redesigns the architecture; the manager never duplicates the coder.
- **Git** — manager only. No milestone commit until implementation is complete, tests pass, blocking review issues are resolved, and status docs are updated. No force push, no history destruction, no secrets.
- **Security** — never expose, log, or commit keys, passwords, tokens, or credentials. Use `.env` + `.env.example`. No real consequential integrations unless the requirements explicitly authorize them.
