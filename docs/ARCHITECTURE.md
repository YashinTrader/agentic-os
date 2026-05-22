# Agentic OS — Phase 1 Architecture

## 1. Purpose
Phase 1 establishes a **local-first, file-based control plane** that lets multiple
independent coding/research agents (Codex, Cursor, Claude, Gemini, Hermes, and
future additions) work toward shared goals **before** any direct agent-to-agent
communication layer exists.

The shared Git repository is the temporary message bus. All coordination —
tasks, assignments, handoffs, decisions, logs — is expressed as structured
files that any agent can read and write.

## 2. Design Principles
1. **Local-first.** Everything lives in the repo. No external services required in Phase 1.
2. **File-based coordination.** Markdown for human/agent-readable docs; JSON/YAML
   for machine-parseable state; JSON Lines (`.jsonl`) for append-only logs.
3. **One writer per file at a time.** Concurrency handled via Git (branch + PR
   or commit-then-pull). No file locks.
4. **Human-in-the-loop for risk.** Any destructive or irreversible action
   requires explicit human approval recorded in `decisions/`.
5. **Don't overbuild.** No kernel, no daemon, no scheduler. Just files + Git +
   conventions.
6. **Forward-compatible.** Schemas chosen so a future MCP/API layer can read
   the same files without migration.

## 3. Repository Layout
```
/
├── README.md
├── docs/
│   ├── ARCHITECTURE.md          # this file
│   ├── AGENT_PROTOCOL.md        # how agents read/write
│   ├── TASK_SCHEMA.md           # task file format
│   ├── HANDOFF_PROTOCOL.md      # handoff rules
│   └── DECISIONS.md             # ADR index + log
├── tasks/
│   ├── PHASE_1_TASKS.md         # human-readable backlog
│   ├── active/                  # one YAML file per in-flight task
│   ├── done/                    # archived completed tasks
│   └── blocked/                 # tasks awaiting human/external input
├── handoffs/
│   └── <task-id>__<from>__to__<to>.md
├── decisions/
│   ├── INDEX.md
│   └── ADR-####-<slug>.md
├── logs/
│   ├── agent-events.jsonl       # append-only event log (all agents)
│   └── README.md
├── memory/                      # reserved for Phase 2 (unified memory)
│   └── README.md
└── scripts/
    └── validate.py              # local repository validator
```

## 4. The Five Concepts
| Concept   | File(s)                                  | Owner            |
|-----------|------------------------------------------|------------------|
| Task      | `tasks/active/<id>.yaml`                 | Assigned agent   |
| Handoff   | `handoffs/<id>__<from>__to__<to>.md`     | Outgoing agent   |
| Decision  | `decisions/ADR-####-*.md`                | Claude (reviewer)|
| Event log | `logs/agent-events.jsonl`                | Every agent      |
| Backlog   | `tasks/PHASE_1_TASKS.md`                 | Manager (human)  |

## 5. Agent Roles (Phase 1)
| Agent   | Phase 1 Role                                              |
|---------|-----------------------------------------------------------|
| Codex   | **Primary builder.** Implements tasks, scaffolds code.    |
| Claude  | **Architect/reviewer.** ADRs, difficult decisions, PR review. |
| Cursor  | *Deferred to Phase 2* (frontend/dashboard).               |
| Gemini  | *Deferred to Phase 2.* Optional researcher.               |
| Hermes  | *Deferred to Phase 2.* Local log summarizer.              |
| Human   | **Approver.** Signs off on risky actions and ADRs.        |

## 6. Coordination Flow (Happy Path)
```
Human writes task         → tasks/active/<id>.yaml (status: todo)
Agent picks task          → updates status: in_progress, owner
Agent works, logs events  → appends to logs/agent-events.jsonl
Agent finishes            → writes handoffs/<id>__codex__to__claude.md
                          → updates status: review
Reviewer agent reviews    → writes ADR if needed, approves/rejects
Task closed               → moved to tasks/done/<id>.yaml (status: done)
```

## 7. Concurrency Model
- Each agent works on its **own Git branch** named `agent/<name>/<task-id>`.
- Merges to `main` happen via PR (human-approved in Phase 1).
- Append-only files (`logs/agent-events.jsonl`, `decisions/INDEX.md`) use
  one-line-per-event format to minimize merge conflicts.
- If conflict occurs on a task YAML, the **agent loses** — it must re-read
  `main`, re-plan, and try again.

## 8. Safety Rails
- **No agent may merge to `main`.** Only humans merge.
- **Risky actions** (defined in `AGENT_PROTOCOL.md` §5) require an ADR with
  `approval: human` before execution.
- Every action is logged. No silent operations.

## 9. Out of Scope (Phase 1)
- Unified semantic memory (Mem0/Cognee) — Phase 2.
- Live dashboard / Kanban UI — Phase 2 (Cursor's work).
- Direct agent-to-agent messaging — Phase 3.
- Token/quota monitoring — Phase 2.
- Auto-routing / agent selection — Phase 3.

## 10. Success Criteria for Phase 1
- Codex can pick up a task YAML, work on it, write a handoff, and log events
  without human prompting beyond the initial assignment.
- Claude can review a handoff and produce an ADR.
- Any new agent can be onboarded by reading `AGENT_PROTOCOL.md` alone.
- Zero merge conflicts on the event log over a 1-week trial.
