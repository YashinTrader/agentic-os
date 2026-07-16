# Autonomous Local Builder

Agentic OS can run bounded Codex development tasks in isolated Git worktrees using a **standing execution policy** (`auto_local_worktree`). Task activation is the authorization; per-run human approval is not required for this mode.

## Standing policy

Configuration: `config/execution-policy.yaml`

- Mode: `auto_local_worktree`
- Adapter: `codex-restricted`
- Maximum concurrent runs: 1
- Automatic worktree allocation, execution, verification, and handoff
- No merge, push, deploy, MCP, or production access

## What Codex may do

- Read the repository (context bundle + worktree checkout)
- Edit files inside the allocated worktree (task `execution.allowed_paths`)
- Run verification commands and tests
- Produce a structured handoff in the worktree

## What Codex may not do

- Modify the canonical checkout
- Merge, push, or force Git operations
- Deploy or access production systems
- Run MCP tools or browser automation
- Read approval-signing keys or unrelated secrets

## Dedicated route

Codex runs only through:

- `scripts/run_codex_builder.py` (single task)
- `scripts/run_local_builder_worker.py` (poll / `--once`)

Generic dispatch (`execute_dispatch.py`) remains blocked for `codex-restricted`.

## Results

Artifacts are recorded under `runtime/dispatch/runs/<run_id>/` including `result.json`, logs, diff, verification output, and handoff copy.

Merge and deployment remain manual operator steps after review.