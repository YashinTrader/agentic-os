# Codex Local Builder Runbook

## Create an executable task

Add a task under `tasks/active/` with:

```yaml
execution:
  mode: auto_local_worktree
  adapter: codex-restricted
  timeout_seconds: 1800
  allowed_paths:
    - dashboard/**
    - tests/**
  forbidden_operations:
    - git_push
    - git_merge
    - deploy
verification:
  commands:
    - python scripts/validate.py
  run_full_tests: true
status: ready
requires_human_approval: false
```

## Run one task

```text
python scripts/run_codex_builder.py --task tasks/active/<TASK>.yaml --json
```

## Start the worker (manual)

Process one eligible task:

```text
python scripts/run_local_builder_worker.py --once
```

Poll continuously until Ctrl+C:

```text
python scripts/run_local_builder_worker.py
```

## Inspect results

- Run directory: `runtime/dispatch/runs/<run_id>/`
- Worktree path: `worktree_allocation.json` and `result.json`
- Diff: `git_diff.patch`
- Handoff: `handoff.md` (copy) and worktree `handoffs/`

## Merge accepted work (manual)

1. Review worktree diff and handoff
2. Run tests/validator locally if needed
3. Cherry-pick or copy changes into your integration branch
4. Commit and push manually — the builder never merges or pushes

## Stop / disable

- Worker: Ctrl+C
- Disable Codex globally: set `enabled: false` in `config/execution-policy.yaml` or deactivate the adapter in registry

## Requirements

- Installed Codex CLI (`codex-cli 0.136.0+`)
- `OPENAI_API_KEY` in environment (never logged by the runner)