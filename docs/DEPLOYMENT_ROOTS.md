# Deployment configuration and mutable state

Run pinned deployment code with:

```powershell
python <pinned-checkout>/scripts/run_supervisor_layers.py --state-root <target-checkout>
```

The config root defaults to the checkout containing the entrypoint scripts,
regardless of `--state-root` or legacy `--root`. Override it with `--config-root`
or `AGENTIC_OS_CONFIG_ROOT`; the explicit flag wins. It must contain both
`agents/` and `config/`. This ensures a pinned release reads its own adapter
isolation flags, execution policy, quota-probe authorization, and deadlines.
Registries in `roles/`, `teams/`, `skills/`, and `mcps/` follow the same root.
There are currently no runtime disk readers for `prompts/` or `schemas/` in
the supervisor layers; reviewer prompts and schemas are Python code constants.
Any new versioned configuration reader must use `root_paths.resolve_config_root`.

Mutable `runtime/`, `logs/`, `tasks/`, and `handoffs/`, assignment/wake queues,
runs, locks, and the Git repository used as the base for worktree allocation
remain under the state root. Worktrees retain their existing sibling-directory
or `AGENTIC_OS_WORKTREE_ROOT` placement. State-root selection remains explicit
`--state-root`, then `AGENTIC_OS_STATE_ROOT`, then legacy `--root`/entrypoint
checkout. Only `runtime/` is required there; versioned agents are unnecessary.

The parent passes both flags to the builder and Claude consumer and exports
both root variables. Direct layer entrypoints also export the selected roots.
The agent environment allowlist preserves these two non-secret paths, so
probes, reviewer processes, launchers, and their helpers share the selection.
Library callers without a config-root environment override continue reading
configuration from their supplied repository root, including partial test
fixtures; deployment entrypoints always validate the config checkout.

Each layer records `config_root`, `config_root_git_sha`, and `state_root` in
its status: `runtime/dispatch/layer_supervisor/status.json`,
`runtime/dispatch/supervisor_status.json`, and
`runtime/dispatch/claude_event_consumer/status.json`. A non-Git config directory
or failed local Git query reports a null SHA. The SHA identifies HEAD, not
uncommitted changes; deploy a clean pinned checkout for reproducible config.

For deployment checks against old runtime state, inspect the consumer's current
`lifecycle_state` and `stale_claims` independently. Legacy claims remain fenced
and alert even while newer work resolves. See
[consumer claim recovery](CONSUMER_CLAIM_RECOVERY.md) for the audited claim and
review-lease operator commands; run them against the selected state root.

## Maintenance, deployment restart and rollback

Use the pinned checkout's local stop control for planned maintenance. Set the
maintenance fence and request a stop in one command, using the same state root
as the Scheduled Task:

```powershell
python <pinned-checkout>/scripts/stop_supervisor.py --state-root <state-root> --maintenance on --actor Gabriel --reason "deployment maintenance" --timeout 90
```

Exit 0 means the recorded supervisor and child identities are gone. Exit 3
means the grace/wait deadline expired and the recorded owned tree was forcibly
terminated; this is reported in stdout and the audit. Exit 2 means refusal or
failure: inspect the audit and do not begin cleanup while any process remains.
The default wait is 90 seconds. Do not use `schtasks /End` to stop the Python
tree, or select processes by executable name with `taskkill`.

The maintenance fence is `runtime/dispatch/layer_supervisor/maintenance.json`.
While it exists, Scheduled Task repetitions exit 0 with "maintenance mode"
without starting layers. Keep it set throughout cleanup or changing the pinned
release. The stop request records requester, reason, token, time and target
instance in `stop_request.json`; durable per-operation results and verified
process identities are retained under `layer_supervisor/audit/<token>.json`.
Do not delete these files as part of cleanup. Stale requests cannot stop a new
instance. Do not remove `instance.lock` or `control.lock`: they are OS-locked
files, released automatically on process exit, rather than stale PID files.

Shutdown uses the existing planned-stop behavior: each child layer receives
CTRL_BREAK and up to 20 seconds to unwind, then its owned Job Object is
terminated, including surviving descendants. In-flight builder work is
interrupted; its process monitor terminates the owned agent tree before
unwinding. In-flight reviews are cancelled and release their review lease;
the consumer claim is finalized by its existing cleanup. This does not finish
or approve assignments. If the grace period is exhausted, cleanup handlers
may not finish. Run states can retain their last running identity until
existing orphan/claim recovery classifies them. Prompts, stdout, stderr,
worktrees, run records and prior review-attempt evidence are preserved.
Inspect these and existing recovery fences before retrying interrupted work.

After cleanup, clear the fence, then let the Scheduled Task start the selected
release (or run its entrypoint once):

```powershell
python <selected-checkout>/scripts/stop_supervisor.py --state-root <state-root> --maintenance off
python <selected-checkout>/scripts/run_supervisor_layers.py --state-root <state-root> --config-root <selected-checkout>
```

Maintenance-only `--maintenance on`/`off` does not stop a running supervisor.
Adding `--actor` and `--reason` makes it a stop request, including when combined
with `--maintenance on`. A second supervisor for the same root is refused by
an OS instance lock and validated root PID/creation-time status. The stop
control uses creation identities for every recorded child and revalidates the
root immediately before forced termination. On Windows it additionally checks
membership in the recorded named Job before terminating that Job, so the
venv shim/interpreter tree is covered. Unreadable or reused root identities
are refused, never signaled. Supervisors predating this control need a separately
validated legacy shutdown; missing identity evidence is deliberately refused.

For rollback, repeat the fenced stop, select the old pinned checkout, clear
maintenance and start the old entrypoint. Verify `status.json` has the new root
PID/creation time, expected `config_root_git_sha`, and advancing child ticks
after each start. Complete each stop before starting another release.
