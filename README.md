# Agentic OS — Phase 1

A **local-first, file-based control plane** for coordinating multiple AI
coding/research agents (Codex, Cursor, Claude, Gemini, Hermes, …) using a
shared Git repository as the temporary communication layer.

> Phase 1 is intentionally minimal. No daemons, no APIs, no databases.
> Just files, Git, and a strict protocol every agent follows.

## Why
Most agents (Codex, Claude Code, Cursor, etc.) cannot yet talk to each other
directly. But they *can* all read and write files in a Git repo. Phase 1
exploits that: every coordination primitive — tasks, assignments, handoffs,
decisions, logs — is a structured file.

## Quick Tour
| Directory      | What lives here                                      |
|----------------|------------------------------------------------------|
| `docs/`        | The protocol. Read these first.                      |
| `tasks/`       | Backlog and in-flight work (YAML files).             |
| `handoffs/`    | One markdown file per agent-to-agent transition.     |
| `decisions/`   | ADRs (architectural decision records).               |
| `logs/`        | Append-only event log (`agent-events.jsonl`).        |
| `memory/`      | Reserved for Phase 2 (unified semantic memory).      |
| `scripts/`     | Local validation tooling for Phase 1 files.           |
| `daemon/`      | Phase 2.0 runtime CLI discovery (observe-only).       |
| `runtime/`     | Machine-readable daemon inventory and status.         |

## Start Here (Humans)
1. Read `docs/ARCHITECTURE.md` — the big picture.
2. Read `tasks/PHASE_1_TASKS.md` — what's being built right now.
3. Assign a task by editing its YAML `owner` field and committing.

## Start Here (Agents)
**You must read these files before taking any action:**
1. `docs/AGENT_PROTOCOL.md` — the binding contract.
2. `docs/TASK_SCHEMA.md` — how tasks are structured.
3. `docs/HANDOFF_PROTOCOL.md` — how to end a work session.
4. `docs/DECISIONS.md` — when and how to write ADRs.

Then:
- Check `tasks/active/` for tasks where `owner: <your-id>`.
- Work on branch `agent/<your-id>/<task-id>`.
- Log every significant action to `logs/agent-events.jsonl`.
- Write a handoff before you stop.

## Agent Roles (Phase 1)
- **Codex** — primary builder (implements Phase 1 tasks).
- **Claude** — architect/reviewer (writes & approves ADRs).
- **Cursor / Gemini / Hermes** — deferred to Phase 2.
- **Human** — approves risky actions, merges PRs.

## Safety
- No agent may merge to `main`. Humans merge.
- Risky actions require an ADR with `approval: human`.
- Every action is logged. No silent operations.

## Phase 1.5 CLI Helpers
Small local helpers are available for common file-based operations:

```powershell
python scripts/create_task.py --id T-0013 --title "Example" --objective "Describe the work."
python scripts/list_tasks.py
python scripts/update_task.py --id T-0013 --status in_progress
python scripts/append_log.py --agent codex --task T-0013 --event started
python scripts/create_handoff.py --task T-0013 --from-agent codex --to-agent claude --what-i-did "Summarized work."
```

Run `python -m unittest` and `python scripts/validate.py` before handoff.

## Phase 2.0 — Runtime Daemon (CLI Discovery)
A local discovery daemon inventories installed CLIs and agent tools, writes
`runtime/registry/cli_inventory.yaml`, and exposes the inventory in the dashboard
**Agents / Tools** tab. Observe-only — no agent launching yet.

```powershell
python -m daemon.daemon --once
python dashboard/app.py
```

See `docs/DAEMON_DISCOVERY.md` for safety guarantees and limitations.

## Phase 2 (Later)
- Phase 2.1 — Skills + MCP Registry (read-only inventory extension).
- Unified semantic memory (Cognee or Mem0) via MCP.
- Hermes summarizes the event log nightly.
- Token/usage monitoring per agent.

## License
TBD (decide in ADR before Phase 2).
