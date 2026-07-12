# Composer / Grok Build local builder — preview + assignment loop

**Display name:** Grok Build (Grok 4.5)  
**Stable ids:** adapter `composer-restricted`, agent `composer`, route `composer_local_builder`.

Phase 3.8 delivered design + scaffolding. **Phase 3.8B activates the file-based
assignment loop** (manual pickup). Automatic execution remains off.

## What works today

- Adapter registry entry and `agents/composer_restricted_adapter.yaml` (`supports_execution: false`)
- Route policy recognizes `composer_local_builder` alongside `codex_local_builder`
- Full assignment contract + claim lifecycle in `dispatch/assignment_channel.py`
- CLI: `python scripts/assignments.py list|show|claim|complete|ingest|create`
- Dashboard Execution Runs tab shows full lifecycle (read-only)
- Operating contract: `docs/GROK_BUILD_LOOP.md`
- ADR-0043 documents invocation interface and Gabriel-gated live activation

## What does not run yet

- `composer-restricted` is **not** in `config/execution-policy.yaml` `enabled_adapters`
- No Grok/Composer subprocess invocation
- No API keys or network calls to Grok endpoints

## Claude assigns work

```bash
python scripts/assignments.py create --from-task tasks/active/T-MY-TASK.yaml --assigned-by claude
```

Or:

```python
from pathlib import Path
from dispatch.assignment_channel import write_assignment

write_assignment(
    Path("."),
    task_id="T-MY-TASK",
    title="My task",
    goal="…",
    base_branch="main",
    task_path="tasks/active/T-MY-TASK.yaml",
    assigned_by="claude",
)
```

Grok Build session: `python scripts/assignments.py claim` then build, then
`python scripts/assignments.py complete …`. Claude: `python scripts/assignments.py ingest`.

## Live activation follow-up (Gabriel gate)

1. Gabriel approves Grok credentials
2. Add `composer-restricted` to `enabled_adapters`
3. Wire inbox poller + adapter command builder
4. Set `supports_execution: true` only after credential gate

See `decisions/ADR-0043-composer-grok-build-integration.md` and `docs/GROK_BUILD_LOOP.md`.