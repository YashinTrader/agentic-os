# Physical Agent Launcher (Phase 3.9.1)

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
5. An unchanged quota/auth fingerprint does **not** relaunch on the next wake.
   The supervisor tick may relaunch it later under the condition-retry cap below.

## Condition retry (quota / auth)

Builder runs blocked on quota or authentication record `blocked_on`
(`quota:<provider>` or `auth:<provider>`), `blocked_since`, `next_eligible_at`,
and `attempts` on the run record. The supervisor tick re-evaluates them without
a new wake. A run becomes eligible when its parsed `retry_after` elapses, when
the exponential backoff elapses (15 minutes, doubling, capped at 6 hours), or
when a quota-free probe succeeds. Probes run at most once per provider per 10
minutes. Each eligibility window relaunches once. A `retry_after` that is no
longer in the future does not open another immediate window; the next wait is
the backoff. The relaunch reuses the preserved
worktree, branch, and work lock, and still uses the M1-04B deadlines. The
relaunch emits one terminal poke when that attempt ends.

Automatic condition retries stop at 4 per run (configurable). The run then
becomes `blocked_external` and an alert is written to
`runtime/dispatch/builder_condition_alerts.json`. Orchestrator `supersede`
still replaces the held work lock, and a changed fingerprint can still relaunch
through the existing wake path.

Probes, from the installed CLIs (no model invocation):

| Provider | Probe | Notes |
|---|---|---|
| grok / composer | none | `grok status` opens the TUI. There is no non-mutating status command, so Grok waits on backoff or `retry_after` only. |
| codex | `codex login status` | Resolved executable, `shell=False`, success is exit code 0. This sees login, not quota, so it clears `auth:codex` only. |
| claude | `claude auth status` | Same M1-02 probe; only `auth:claude` with `loggedIn: true`. |

`recovered_at` and `recovery_seconds` record the interval from `blocked_since`
to the first genuine activity of a successful condition relaunch.

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
