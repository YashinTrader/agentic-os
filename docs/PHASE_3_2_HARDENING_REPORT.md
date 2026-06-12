# Phase 3.2 Hardening Report

**Date:** 2026-06-12  
**Author:** composer

## Tests Added

| Module | Coverage |
|--------|----------|
| `test_phase3_1_cleanup.py` | Approval split, MCP metadata, field messages, TTLs |
| `test_dispatch_execution_gate.py` | All hard gate rules |
| `test_dispatch_executor.py` | Dry-run, execute, subprocess isolation, dashboard |
| `test_dispatch_runtime_capture.py` | Run directory artifacts |
| `test_dispatch_approval_store.py` | Record create/load, satisfaction |
| `test_dispatch_worktree_policy.py` | Path sandbox, worktree block |

## Safety Invariants

1. `subprocess` only in `dispatch/executor.py` (production) + tests
2. `preview.py` has no subprocess
3. Dashboard dispatch tab is read-only (no action buttons)
4. `--execute` required for subprocess; `--dry-run` never subprocess
5. Only `local-python-exec-test` has `supports_execution: true`
6. Event types emitted ⊆ `ALLOWED_EVENT_TYPES`

## Known Limitations

- Worktrees are not auto-created; file-writing execution blocked without configured worktree
- CLI inventory may be empty in dev; executor blocks when `required_clis` present
- No signing/auth on approval records (Phase 3.1 design scope)
- Timeout enforcement via `subprocess.run(timeout=...)`

## Remaining Risks

- Operator could pass `--execute` on safe adapter with crafted preview if gates have gaps
- Approval records are file-based without cryptographic binding
- Real CLIs remain in registry as `active` for preview but not execution

## For Claude Final Review

- Verify no autonomous execution paths
- Verify gate completeness vs `docs/PHASE_3_2_REVIEW_PACKET.md`
- Confirm adapter registry policy (only test adapter executes)
- Review event vocabulary alignment