# Phase 3.3 — Runtime Governance (Resources, Sessions, Monitoring)

**Status:** design only

## Resource and concurrency model

| Policy | Default (proposed) |
|--------|-------------------|
| Global concurrent runs | 2 |
| Per-agent concurrent runs | 1 |
| File-writing runs per repo | 1 (requires worktree) |
| CPU budget | OS process limits; no cgroup in MVP |
| Memory budget | Adapter-declared; monitor via process |
| Time budget | `timeout_seconds` per adapter (enforced in 3.2) |
| Token/API budget | Manual tracking; provider metering when available |
| Queue priority | P0 > P1 > P2 > P3 task priority |

## Cancellation semantics

- Operator sends cancel → SIGTERM to child process group.
- Grace period 10s → SIGKILL if still running.
- Orphan cleanup scans `runtime/dispatch/previews/*/result.json` for `executed: true` without terminal state.
- Stale run detection: no heartbeat for 2× timeout → mark failed.

## Agent session and handoff lifecycle

1. Allocate isolated workspace (future worktree).
2. Compile context from orchestrator.
3. Record preview (`runtime/dispatch/previews/<run_id>/`).
4. Collect approval (bound to preview).
5. Start session (subprocess or agent SDK).
6. Stream/capture stdout/stderr.
7. Detect completion / failure / timeout.
8. Inspect file changes.
9. Generate handoff markdown.
10. Require reviewer pass.
11. Preserve artifacts under `runtime/dispatch/previews/<run_id>/`.
12. Optional cleanup per policy.

**Completion is not exit code alone.** Required artifacts:

- Handoff file exists.
- Verification results recorded.
- Changed-file inventory for writers.

## Monitoring and budget model

Future dashboard/daemon telemetry (read-only in Phase 3.3):

| Signal | Source |
|--------|--------|
| Running agents | `result.json` + process table |
| Queued runs | Future queue file |
| Duration | `created_at` → completion timestamp |
| Timeout | `timed_out` in result |
| Exit codes | `exit_code` in result |
| CLI availability | `runtime/registry/cli_inventory.yaml` |
| stdout/stderr | Per-run artifact paths |
| Files changed | Future diff inventory |
| Approval status | `approval.json` |
| Token use | Provider API when exposed; else CLI log estimates |
| Cost | Manual / unknown for subscription CLIs |
| Retries | Future queue metadata |
| Failure reason | `block_reasons` + stderr tail |

**Honesty constraint:** Subscription quota and token-left data may not be exposed by providers. Design supports exact API metering when available, CLI log estimates otherwise, and `unknown` status when neither is observable. No provider scraping in Phase 3.3.

## Failure recovery and rollback

- Failed runs: preserve worktree + artifacts (`cleanup_policy: preserve_on_failure`).
- Rollback: `git -C <worktree> reset --hard <base_commit>` documented in allocation record.
- No automatic rollback without operator confirmation.
- Event emission failures do not change execution outcome (Phase 3.2.1 behavior).