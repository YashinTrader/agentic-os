# Phase 3.6 Codex Rollback and Emergency Disable

## Immediate disable

When Codex must stop immediately:

1. Set `codex-restricted.supports_execution: false` in `agents/codex_restricted_adapter.yaml` and registry (manual clerical step).
2. Write `runtime/dispatch/codex_emergency_disable.json`:

```json
{"disabled": true, "reason": "<operator reason>", "at": "<ISO8601>"}
```

3. Set activation manifest `status` to `suspended` or `revoked`.
4. Refuse further canary runs (`run_codex_canary.py` gate 12).
5. Preserve worktrees, logs, and manifests — do not delete evidence.

## Canary rollback (no merge)

Because canary runs in an isolated worktree with no merge:

- Canonical repository remains unchanged if canary is not merged.
- Inspect worktree `git status` and diff.
- Remove generated `docs/codex-canary-*.md` if desired after review.
- Remove worktree only after dirty-state review.
- Preserve branch until Claude/human review completes.
- Human approval remains consumed after a live run (anti-replay).

## Failure conditions requiring disable

- Unexpected file modifications outside `docs/codex-canary-*.md`
- File deletions
- Adapter or manifest tampering during run
- CLI version/help drift from reviewed contract
- Timeout exceeded (10–15 minute operator bound)
- Network or token errors indicating uncontrolled scope expansion

## Recovery

1. Document incident in handoff
2. Re-run `python scripts/validate_codex_activation.py`
3. Regenerate CLI compatibility via `python scripts/inspect_codex_cli.py` (read-only)
4. New activation manifest required after any config or command contract change