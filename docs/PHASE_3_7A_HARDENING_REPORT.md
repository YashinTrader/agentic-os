# Phase 3.7A Hardening Report

## Findings

### Critical

None identified in Phase 3.7A implementation.

### High

- **H1 (closed in Phase 3.7A.1):** generic `execute_dispatch.py` could treat `codex-restricted` as a normal executable adapter. Fixed via `dispatch/execution_route_policy.py` and route checks before approval consumption.

### Medium

- Windows `codex.CMD` shim may return partial `exec --help` output; operator must verify CLI on activation host before Phase 3.7B.

### Low

- Runtime activation bundles under `runtime/dispatch/codex_activation/` are generated artifacts; not committed as canonical state.

## Fixes applied

- Phase 3.7A.1: centralized execution-route policy; generic dispatch rejects canary-only adapters
- Fifteen-gate `evaluate_activation_gates()` with mandatory Phase 3.7B check
- `run_codex_canary.py` refuses before subprocess (no `subprocess.run`)
- `disable_codex_canary.py` writes disable record only
- Manifest v2 forbids fabricated approval references in Phase 3.7A
- Phase 3.5/3.6 tests updated for activation candidate state

## Remaining risks

- Misconfigured Phase 3.7B authorization artifact could enable live run; requires separate milestone controls
- CLI version drift between manifest and host requires re-preflight

## Readiness recommendation

**APPROVE** for Claude review of Phase 3.7A activation candidate (no live execution in this milestone).