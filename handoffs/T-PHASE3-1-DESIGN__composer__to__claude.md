# Handoff: T-PHASE3-1-DESIGN — Phase 3.1 controlled executor design contract
**From:** composer  
**To:** claude  
**Date:** 2026-06-11T12:00:00Z  
**Task Status After Handoff:** review

## What I Did

- Created Phase 3.1 design docs: executor lifecycle, approval model, worktree/sandbox strategy,
  runtime capture contract, and review packet.
- Added contract modules (validation only):
  - `dispatch/executor_contract.py` — `ExecutionRequest`, CLI inventory gate,
    `validate_execution_request_contract`
  - `dispatch/approval_contract.py` — `ApprovalRecord`, expiry/revocation rules
  - `dispatch/freshness.py` — `compute_preview_hash`, `is_approval_fresh`, `is_preview_stale`
- Extended `dispatch/preview.py` with KEY=VALUE forbidden key detection
  (`validate_key_value_forbidden_args`, `parse_key_value_token`).
- Reserved Phase 3.2 execution events in `protocol/event_types.py` without adding to
  `ALLOWED_EVENT_TYPES`.
- Added ADR-0014, ADR-0015, ADR-0016 and updated `decisions/INDEX.md`.
- Added JSON schemas under `schemas/`.
- Added 26 tests in `tests/test_phase3_1_*.py`.
- Completed internal builder/reviewer loop (`docs/REVIEW_COMPOSER_PHASE_3_1_DESIGN_SELF_REVIEW.md`).

## What Remains

- Claude final review of Phase 3.1 design (this handoff).
- Phase 3.2 executor implementation **only after** ADR acceptance and explicit task.
- Approval recording operator workflow (file-based or UI).
- Git worktree creation and pre-execution snapshot tooling.
- Runtime log capture implementation under `runtime/dispatch/runs/<run_id>/`.
- Optional: surface CLI inventory gate warnings in Phase 3.0 preview output.

## Decisions Made

- Preview hash covers: command, cwd, scope_paths, adapter_id, task_id, approval_level,
  risk_level (canonical JSON SHA-256).
- `forbidden_args` entries serve dual duty as exact tokens and KEY=VALUE keys.
- `writes_files=true` requires `worktree_required=true` at execution validation (ADR-0016).
- `secrets_required=true` requires `approval_level: human`.
- Phase 3.2 events documented but not enabled in validator allowlist until emitters exist.

## Open Questions

1. Should adapters gain explicit `forbidden_keys` separate from `forbidden_args`?
2. Default approval TTL for reviewer vs human approvals?
3. Should preview builder set `worktree_required` hint when `writes_files: true`?
4. When `cli_inventory.yaml` is missing, should preview downgrade `dispatch_allowed` now or
   only at Phase 3.2 execution gate?

## How to Verify My Work

```bash
python scripts/run_tests.py
python scripts/validate.py
python -m unittest tests.test_phase3_1_executor_contract -v
python -m unittest tests.test_phase3_1_approval_contract -v
python -m unittest tests.test_phase3_1_freshness -v
```

Review:

- `docs/PHASE_3_1_REVIEW_PACKET.md`
- `docs/REVIEW_COMPOSER_PHASE_3_1_DESIGN_SELF_REVIEW.md`
- `decisions/ADR-0014-phase-3-1-controlled-executor-contract.md`
- `decisions/ADR-0015-approval-recording-and-preview-freshness.md`
- `decisions/ADR-0016-worktree-sandbox-before-file-writing-execution.md`

Grep safety:

```bash
rg "import subprocess|subprocess\.|os\.system" dispatch/executor_contract.py dispatch/approval_contract.py dispatch/freshness.py dispatch/preview.py
```

## Risks / Caveats

- No subprocess execution added; Phase 3.1 is contract-only.
- KEY=VALUE parsing uses first `=` split; unusual CLI formats may need adapter notes.
- `codex-cli-preview` has `writes_files: true` with `repo_root` policy — execution contract
  blocks without worktree; preview cwd may look permissive.
- Self-review fixed staleness hash to prefer live task context (F1).

## Recommended Next Action for Receiver

1. Review ADR-0014/0015/0016 and design docs against ADR-0012 gates.
2. If approved, mark Phase 3.1 design **READY FOR PHASE 3.2 IMPLEMENTATION REVIEW** with a
   new explicit implementation task (not autonomous dispatch).
3. Resolve open questions on `forbidden_keys` and CLI inventory preview surfacing before
   executor coding starts.