# Phase 3.7A Live Run Prohibition

## Hard boundary

Phase 3.7A **must not** run Codex on a prompt. The canary runner refuses all live execution paths.

## Runtime fields

- `live_run_authorized: false` on adapter and manifest
- `phase3_7b_authorization_required: true`
- `phase3_7b_authorization.json` **absent**

## Blocked reason

```text
Phase 3.7B human authorization has not been recorded.
```

## Runner behavior

`scripts/run_codex_canary.py`:

- Always returns exit code **3**
- Sets `codex_subprocess_invoked: false`
- Sets `approval_consumed: false`
- Sets `stops_before_step: 16`
- Never calls `subprocess.run` for Codex

## Future authorization (Phase 3.7B only)

```text
runtime/dispatch/codex_activation/<activation_id>/phase3_7b_authorization.json
```

This file must not be created during Phase 3.7A.

## Tests prove

- `supports_execution: true` alone does not run
- Manifest alone does not run
- Fake human approval alone does not run
- `--execute-canary` alone does not run
- All gates except Phase 3.7B still block when authorization absent