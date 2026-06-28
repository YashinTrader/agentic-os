# Phase 3.7A Canary Preflight

## Read-only CLI discovery

Allowed commands on the activation host:

```text
codex --version
codex --help
codex exec --help
```

Invocation rules:

- Fixed argv list, `shell=False`, bounded timeout, captured stdout/stderr
- **No prompt** passed to `codex exec`

## Compatibility record

Path: `runtime/registry/codex_cli_compatibility.json`

Verified fields:

- executable exists (when installed)
- parsed version
- `exec` subcommand present
- `-C` / cwd option
- `-s` / sandbox option
- `--json` and `-o` output option
- `workspace-write` sandbox mode
- help hash recorded

## Per-activation preflight

Path: `runtime/dispatch/codex_activation/<activation_id>/preflight.json`

Records:

- `preflight_complete_no_live_run`
- `worktree_allocated: false` (unless operator-commanded separately)
- `codex_subprocess_invoked: false`

## Incompatible CLI

If installed CLI is incompatible:

- Do not weaken the command contract
- Do not activate
- Report exact incompatibility in validation output

Repository validation must pass when Codex is absent.