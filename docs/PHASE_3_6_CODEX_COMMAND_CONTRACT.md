# Phase 3.6 Codex Command Contract

## CLI semantics (discovered)

```
codex exec [OPTIONS] [PROMPT]
```

- **Subcommand:** `exec` (non-interactive)
- **Sandbox:** `-s workspace-write`
- **Output:** `-o` / `--output-last-message <FILE>` — agent final message path
- **Prompt:** trailing positional argument after all options

## Canonical argv shape

```text
[
  "codex",
  "exec",
  "--ignore-user-config",
  "-c", "mcp_servers={}",
  "-C", "<worktree_path>",
  "-s", "workspace-write",
  "--json",
  "-o", "<agent_output_path>",
  "<prompt>"
]
```

MCP isolation (Phase 3.9.5): see `docs/MCP_ISOLATION_POLICY.md`. Default
`required_mcp_servers: []` injects `--ignore-user-config` and
`-c mcp_servers={}` so user-level optional MCP servers cannot abort unrelated
runs.

## MA1 fix

Prior defect assigned `argv[-1] = prompt_arg`, overwriting the `-o` value token. Phase 3.6 uses `append_codex_prompt()` so the output path immediately after `-o` is preserved.

## Invariants (regression-tested)

1. `-o` appears exactly once
2. Token after `-o` is the agent output path
3. Prompt appears exactly once
4. Prompt is the trailing positional argument
5. Prompt does not replace any flag value
6. Output path is not the prompt
7. Spaced prompts remain a single argv token
8. Builder returns argv list (no shell string)
9. Unknown options are blocked
10. Forbidden bypass flags are blocked

## Contract hash

`dispatch/codex_adapter.compute_command_contract_hash()` binds the options template and prompt mode for activation manifests.

## Forbidden flags

- `--dangerously-bypass-approvals-and-sandbox`
- `--dangerously-bypass-hook-trust`