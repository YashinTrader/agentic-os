# Physical Agent Launcher (Phase 3.9.1)

## Layering

The supervisor is the **execution layer**. Completion pokes are the **notification layer**.
Both stay enabled — see `docs/AUTONOMOUS_LOOP_LAYERS.md`.

- Wake queue / PID / run records → execution
- Outbox + `awaiting_review` + orchestrator poke → completion + notification
- Never treat a poke as a launched process; never treat a PID as assignment completion

## What shipped

A persistent local supervisor that turns wake records into **real agent processes**.

```
assignment created
  → wake record queued
  → supervisor receives wake
  → atomic claim + concurrency lease (max 1)
  → Grok Build process launched (shell=False)
  → PID / run state recorded (running only after PID exists)
  → stdout/stderr captured
  → completion → awaiting_review
  → poke orchestrator (Claude only)
```

The passive `scripts/watch_assignments.py` path only claims. It is **not** a physical launcher.

## Components

| Path | Role |
|------|------|
| `scripts/run_orchestrator.py` | Operator entrypoint (`--once` or persistent) |
| `orchestrator/supervisor.py` | Wake pickup, claim, launch orchestration |
| `orchestrator/agent_launcher.py` | Grok argv builder + Codex fallback plan |
| `orchestrator/runtime_store.py` | Durable run state under `runtime/dispatch/runs/` |
| `orchestrator/process_monitor.py` | Heartbeat, timeout, orphan recovery |
| `orchestrator/failure_classify.py` | Auth/quota classification + fingerprints |
| `orchestrator/leases.py` | Concurrency=1 + per-assignment launch lease |
| `orchestrator/event_router.py` | `awaiting_review` + Claude-only poke |

## Supervisor command

```bash
# One wake
python scripts/run_orchestrator.py --once --agent composer

# Persistent (Ctrl+C clean stop)
python scripts/run_orchestrator.py --agent composer --poll-seconds 5 --max-turns 30 --timeout-seconds 1800
```

Optional:

- `--worktree <path>` — bind launch cwd to an isolated worktree
- `--grok-executable <path>`
- `--codex-executable <path>`
- `--no-codex-fallback`

## Grok launcher command shape

Grok Build **0.2.101** non-interactive form used:

```text
grok --cwd <worktree> --max-turns <N> --output-format json --single "<prompt>"
```

Properties:

- argv array, `shell=False`
- bounded `--max-turns`
- no `--always-approve` / `bypassPermissions` / dangerous bypass flags
- no automatic merge, push, or deploy
- secrets redacted in persisted `command_redacted`

## Codex fallback

When Grok is `blocked_quota`, `blocked_authentication`, `blocked_no_adapter`, or unavailable:

1. Record the primary failure fingerprint
2. At most **one** Codex fallback launch via existing `build_codex_command` surface
3. Preserve lineage (`fallback_from_run_id`)
4. No builder-to-builder reassignment of the assignment contract (Claude remains authority)
5. Unchanged failure fingerprints do **not** relaunch

## Process states

`queued` → `launching` → `running` → (`completed` | `blocked_*` | `failed*` | `timed_out` | `orphaned`)

`running` requires a real PID.

## Dashboard

Execution Runs tab is read-only and now surfaces:

- process state / lifecycle label (`actually_running`, `blocked_external`, …)
- PID / session
- heartbeat timestamp
- blocked reason

No execute/merge/push/deploy buttons.
