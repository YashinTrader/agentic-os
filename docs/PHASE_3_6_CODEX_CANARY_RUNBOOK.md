# Phase 3.6 Codex Canary Runbook (Prepared — Not Executed)

## First canary scope

**Documentation-only.** Create exactly one file in the allocated worktree:

```text
docs/codex-canary-<run-id>.md
```

Allowed content:

- Canary run ID
- Timestamp
- Fixed sentence: `Codex documentation-only canary confirmed.`
- No code, configuration, dependencies, or secrets

## Preparation (Phase 3.6 — allowed)

```bash
python scripts/prepare_codex_canary.py \
  --run-id <run-id> \
  --reviewed-sha <sha> \
  --base-sha <sha> \
  --cli-version 0.136.0
```

This writes preview and draft manifest under `runtime/dispatch/` only. **Does not execute Codex.**

## Execution (Phase 3.6 — blocked)

```bash
python scripts/run_codex_canary.py --execute-canary
```

Always exits **3 (refused)** while `supports_execution: false`.

## Layered gates (all must pass for future live run)

1. Explicit activation marker
2. `supports_execution: true`
3. Compatible promotion state
4. Reviewed activation manifest
5. Human HMAC approval
6. CLI compatibility record
7. Valid worktree allocation
8. Canary contract hash match
9. `--execute-canary` operator flag
10. Maximum run count (1)
11. Anti-replay (approval not consumed)
12. Emergency-disable flag unset

## Post-run inspection (future)

1. Verify exactly one new file under `docs/codex-canary-*.md`
2. No other tracked file changes
3. Preserve worktree and logs until review completes
4. Do not merge or push from canary worktree