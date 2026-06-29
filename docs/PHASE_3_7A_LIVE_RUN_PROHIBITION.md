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

## Phase 3.7A.1 route enforcement (H1 closeout)

**Before Phase 3.7A.1:** the dedicated canary runner blocked live Codex execution, but the generic `execute_dispatch.py` path did not enforce canary-only routing. Absent human approval prevented immediate exploitation; a valid signed approval could have reached Codex through generic dispatch once other gates passed.

**After Phase 3.7A.1:** generic dispatch categorically rejects canary-only adapters (including `codex-restricted`) with reason *"Adapter requires its dedicated canary runner; generic dispatch execution is prohibited."* This holds even when Phase 3.7B authorization exists. Codex may run only through `scripts/run_codex_canary.py`, which remains live-run blocked until Phase 3.7B. No live Codex execution has occurred.