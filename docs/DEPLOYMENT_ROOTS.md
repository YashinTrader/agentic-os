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
