# Handoff: T-PHASE3-3-DESIGN — Phase 3.2.1 hardening + Phase 3.3 design
**From:** composer
**To:** claude
**Date:** 2026-06-19T16:00:00Z
**Task Status After Handoff:** review

## What I Did

- Implemented Phase 3.2.1 controlled executor hardening on branch `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN`.
- Added `dispatch/path_containment.py` with `path_is_inside()` using `Path.resolve()` and `relative_to()` (no string prefix checks).
- Added `dispatch/worktree_policy.py`, `dispatch/freshness.py`, `dispatch/approval.py`, `dispatch/executor.py`, and `scripts/execute_dispatch.py`.
- Made preview freshness failures blocking with structured `preview freshness cannot be verified: …` reasons.
- Required `supports_execution` on all adapters; only `local-python-exec-test` is `true`.
- Surfaced event emission failures via `event_emit_errors` in `result.json` and per-run `events.jsonl`.
- Published Phase 3.3 design docs, ADR-0020–ADR-0024, and JSON schemas (no operational implementation).
- Added tests: `test_worktree_policy.py`, `test_dispatch_executor.py`, `test_phase3_2_1_hardening.py`, `test_phase3_3_design.py`.
- Fixed test `copytree` ignores to exclude `.venv-win` (prevents suite timeouts on Windows).

## What Remains

- Claude final review of Phase 3.2.1 + Phase 3.3 design.
- Phase 3.4 implementation: worktree allocator, HMAC approval signing (per design).
- Real-agent adapter promotions per ADR-0023 (none activated in this milestone).

## Decisions Made

- Windows-safe `local-python-exec-test` command uses `python -c print('dispatch-test-ok')` without nested double quotes so `shlex.split` yields a runnable `-c` argument on Windows.
- Phase 3.2 execution events (`dispatch_started`, `dispatch_completed`, `dispatch_failed`) added to `ALLOWED_EVENT_TYPES` because the controlled executor now emits them for the fixture only.
- Autonomy level remains **Level 1**; scheduling design documents Level 2+ as future-only.
- MVP approval signing recommendation: HMAC with OS keyring secret (Phase 3.4), not implemented now.

## Open Questions

- Should `daemon/cli_discovery.py` subprocess usage be explicitly documented as non-dispatch in safety grep docs (pre-existing)?
- When promoting first real CLI adapter, should worktree allocation be mandatory for all adapters or only `writes_files: true`?

## How to Verify My Work

```bash
python scripts/run_tests.py
python scripts/validate.py
```

Check:

- `runtime/unittest_last_run.txt` → `exit_code: 0`
- `agents/adapter_registry.yaml` → only `local-python-exec-test` has `supports_execution: true`
- `dispatch/executor.py` is the only dispatch runtime subprocess module
- Phase 3.3 design docs and ADR-0020–0018 exist
- No `dispatch/worktree_allocator.py` or `scheduler/` execution module

## Risks / Caveats

- Approval records remain unsigned JSON (by design until Phase 3.4).
- Command tokenization on Windows remains sensitive to quoting; real adapters need per-platform dry-run tests before promotion.
- Full suite runtime ~6 minutes on this Windows host when `.venv-win` is present in workspace.

## Recommended Next Action for Receiver

Perform final review using `docs/PHASE_3_3_REVIEW_PACKET.md` and `docs/REVIEW_COMPOSER_PHASE_3_2_1_AND_3_3_SELF_REVIEW.md`. If APPROVE, next milestone is Phase 3.4 worktree allocator + approval signing implementation.