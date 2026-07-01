# Composer local builder — preview scaffolding (Phase 3.8)

Composer 2.5 (Grok Build) is registered as `composer-restricted` with dedicated route
`composer_local_builder`. This phase delivers **design + preview-safe scaffolding only**.

## What works today

- Adapter registry entry and `agents/composer_restricted_adapter.yaml` (preview, `supports_execution: false`)
- Route policy recognizes `composer_local_builder` alongside `codex_local_builder`
- File-based assignment channel: `runtime/dispatch/assignments/inbox/` and `outbox/`
- Dashboard Execution Runs tab shows pending Composer assignments (read-only)
- ADR-0043 documents invocation interface and live-activation follow-up

## What does not run yet

- `composer-restricted` is **not** in `config/execution-policy.yaml` `enabled_adapters`
- No Grok/Composer subprocess invocation
- No API keys or network calls to Grok endpoints

## Claude assigns work

```python
from pathlib import Path
from dispatch.assignment_channel import write_assignment

write_assignment(
    Path("."),
    task_id="T-MY-TASK",
    task_path="tasks/active/T-MY-TASK.yaml",
    assigned_by="claude",
)
```

Composer (human session or future poller) reads inbox, builds in a worktree, writes outbox + handoff.

## Live activation follow-up

1. Gabriel approves Grok credentials
2. Add `composer-restricted` to `enabled_adapters`
3. Wire inbox poller + adapter command builder
4. Set `supports_execution: true` only after credential gate

See `decisions/ADR-0043-composer-grok-build-integration.md`.