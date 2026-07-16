# Phase 3.5 Codex Restricted Adapter

## Identity

- **Adapter id:** `codex-restricted`
- **Dedicated config:** `agents/codex_restricted_adapter.yaml`
- **Registry entry:** `agents/adapter_registry.yaml` (separate from `codex-cli-preview`)
- **Promotion state:** `restricted_candidate`
- **`supports_execution`:** `false` (Phase 3.5 invariant)

## CLI discovery

- Executable: `codex` (codex-cli **0.136.0** locally)
- Non-interactive mode: `codex exec`
- Sandbox: `workspace-write` (not `danger-full-access`)
- Output: `--json` (JSONL events), `-o` last message file
- Working directory: `-C <worktree>`

## Modules

| Module | Role |
|--------|------|
| `dispatch/codex_adapter.py` | Pure command builder + preview gates |
| `dispatch/agent_context_bundle.py` | Deterministic context bundle |
| `dispatch/agent_environment.py` | Allowlist/denylist environment |
| `dispatch/agent_result_parser.py` | Normalized execution result |
| `scripts/preview_codex_dispatch.py` | Operator preview CLI |
| `scripts/inspect_codex_cli.py` | Read-only CLI discovery |
| `scripts/run_codex_canary.py` | Canary (refuses until activation) |

## Activation

See ADR-0032. Claude final review must approve before any clerical flip of `supports_execution` to `true`.