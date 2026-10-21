# MCP Isolation Policy (Phase 3.9.5)

## Problem

Optional MCP servers configured in an operator's user-level agent CLI can fail
at process startup (stale OAuth tokens, transport errors) even when the task
never uses those integrations. Evidence: Codex run
`build-20260717T012341Z-T-PHASE3-9-4B-SUPERVISOR-9b5813b8` recorded MCP OAuth
`invalid_token` failures for unused servers while the assignment never declared
MCP requirements.

## Policy

| Rule | Behavior |
|------|----------|
| Default | `required_mcp_servers: []` — launch with **zero** optional MCP connections |
| Explicit allowlist | Only named servers may be connected for that assignment |
| Unlisted failure | Impossible by construction (not connected) |
| Required failure | Classified as `blocked_external` with a reason |
| Config mutation | **Forbidden** — per-invocation overrides only; never rewrite `~/.codex/config.toml` |
| Agent MCP tools | `mcp_execution` remains forbidden for restricted adapters; this policy only controls which servers the *CLI process* may even open |

## Schema

Optional field on task YAML and assignment contract:

```yaml
required_mcp_servers: []          # default
# or under execution:
execution:
  required_mcp_servers: []
```

Validation:

- Must be a list of strings when present
- Each name: `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`
- Duplicates rejected
- Omitted field ≡ empty list

## Codex launch path

Implementation: `dispatch/mcp_isolation.py` + `dispatch/codex_adapter.py`.

Every Codex exec argv injects, immediately after `exec`:

1. `--ignore-user-config` — do not load `$CODEX_HOME/config.toml` (auth still uses `CODEX_HOME`)
2. `-c mcp_servers={}` — config override clearing the MCP server table

When `required_mcp_servers` is non-empty, the launcher may rehydrate **simple**
server definitions (command/args or url) from a **read-only** snapshot of the
operator config into additional `-c mcp_servers.<name>={…}` overrides. Complex
nested shapes (env maps, per-tool approval tables) are not rehydrated; the plan
is blocked with a clear reason rather than silently launching half-configured
servers.

Canonical shape (empty required list):

```text
codex exec
  --ignore-user-config
  -c mcp_servers={}
  -C <worktree>
  -s workspace-write
  --json
  -o <agent_output_path>
  <prompt>
```

Evidence is written to run `command.json` under `mcp_isolation` and
`required_mcp_servers`.

## Grok Build (composer) launch path

**Documented gap.** The installed Grok Build CLI surface exposes `grok mcp`
management commands but no per-invocation equivalent of Codex
`-c mcp_servers={}` / `--ignore-user-config`.

- `build_grok_launch_plan` records `required_mcp_servers` and an isolation note
  (`isolation_mode: unsupported`) on `LaunchPlan.mcp_isolation`
- Argv is **not** mutated with invented flags
- Gap constant: `dispatch.mcp_isolation.GROK_MCP_ISOLATION_GAP`

Until Grok gains an isolation mechanism, composer launches cannot guarantee
zero-MCP by construction. Prefer Codex for MCP-sensitive automation, or keep
operator Grok MCP configs empty for supervised work.

## Failure classification

`orchestrator/failure_classify.classify_process_output` accepts
`required_mcp_servers`. When a required server is declared and stdout/stderr
matches MCP auth/transport failure patterns (or names the server), the result
is:

- `process_state`: `blocked_external`
- `category`: `blocked_external`
- `retry_eligible`: false

Unlisted MCP failures must not reach classification: isolation prevents the
connection. Unit tests encode this with
`simulate_unlisted_mcp_cannot_abort`.

## Non-goals

- Adding new MCP servers to the registry
- Credential storage or OAuth refresh
- Mutating user-level Codex/Grok config
- Allowing `mcp_execution` from restricted adapters

## Related code

| Path | Role |
|------|------|
| `dispatch/mcp_isolation.py` | Schema helpers, Codex flags, Grok gap, failure helpers |
| `dispatch/codex_adapter.py` | Injects isolation into exec argv |
| `dispatch/local_builder_core.py` | Passes task `required_mcp_servers` into command plan |
| `dispatch/assignment_channel.py` | Optional assignment field + validation |
| `orchestrator/agent_launcher.py` | Grok note + Codex fallback isolation |
| `orchestrator/failure_classify.py` | Required-MCP → `blocked_external` |
| `agents/codex_restricted_adapter.yaml` | Allows `-c` / `--ignore-user-config` |
| `agents/composer_restricted_adapter.yaml` | Documents Grok gap |
