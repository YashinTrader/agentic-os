# Phase 3.5 Codex Canary Plan

## Status

**Not executed during Phase 3.5 implementation.** Script exists but refuses by default.

## Preconditions (post-activation)

1. Claude approves Phase 3.5 branch
2. Separate activation task sets `codex-restricted` `supports_execution: true`
3. Operator runs CLI inventory refresh
4. Valid worktree allocation for canary task
5. Human-signed approval bound to preview + context bundle hash

## Procedure (future)

```bash
python scripts/preview_codex_dispatch.py --worktree <path> --json
python scripts/approve_dispatch.py ...  # human approval
python scripts/run_codex_canary.py --execute-canary --allocation <json> --approval <json>
```

## Rollback

- Do not merge canary branch automatically
- Inspect worktree diff and verification results
- `git checkout` / manual revert inside worktree
- Mark allocation `preserved` if dirty; operator resolves

## Abort conditions

- Validator failure in worktree
- Handoff missing
- Scope escape detected
- Approval consumed or expired