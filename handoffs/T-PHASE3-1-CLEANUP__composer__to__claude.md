# Handoff: T-PHASE3-1-CLEANUP — Phase 3.1 contract cleanup
**From:** composer  
**To:** claude  
**Date:** 2026-06-11T14:00:00Z  
**Task Status After Handoff:** review

## What I Did

- **M1:** Split approval validation into `validate_approval_record_shape()` and
  `evaluate_approval_satisfaction()` with structured `status` and `reasons`.
- **M2:** Removed dead substring checks (`"none does not require"`, `"revoked" not in blocked`).
  Revoked/expired/stale now use explicit status values.
- **L1:** Added `resolve_mcp_required()` — uses `adapter_type == "mcp"` only; removed
  `adapter_id.endswith("mcp")` heuristic.
- **L2:** Split `_classify_required_field_issues()` into missing vs invalid; blocked reasons
  use `missing: field` and `invalid: field` prefixes.
- **L3-L5:** Documented decisions:
  - CLI inventory gate at Phase 3.2 executor only (not preview)
  - Preview `worktree_required` advisory; executor enforces hard block
  - Default TTL: human 30m, reviewer 60m
  - Keep `forbidden_args` dual-duty; defer `forbidden_keys` field
- Added preview field `worktree_required` (advisory).
- Updated `is_approval_fresh` to delegate to `evaluate_approval_satisfaction`.
- Flipped Claude sign-off on ADR-0014/0015/0016 per Phase 3.1 design review.
- Added 11 new/updated approval tests + 3 executor tests (225 total).

## What Remains

- Claude re-review of cleanup (this handoff).
- Open **T-PHASE3-2-EXECUTOR** with four implementation blockers from
  `docs/REVIEW_CLAUDE_PHASE_3_1.md`.

## Decisions Made

- Approval shape vs satisfaction are separate concerns (no mixed `valid` special-cases).
- `mcp_required` false when adapter unknown or non-mcp type, regardless of id suffix.
- CLI inventory not checked during preview build (machine-agnostic preview).

## Open Questions

None blocking — all four Phase 3.1 open questions resolved in docs/ADRs.

## How to Verify My Work

```bash
python scripts/run_tests.py
python scripts/validate.py
python -m unittest tests.test_phase3_1_approval_contract -v
python -m unittest tests.test_phase3_1_executor_contract.ExecutorContractTests.test_adapter_id_suffix_does_not_imply_mcp_required -v
```

Review:

- `docs/REVIEW_COMPOSER_PHASE_3_1_CLEANUP_SELF_REVIEW.md`
- `docs/REVIEW_CLAUDE_PHASE_3_1.md` (findings M1-L5)
- `dispatch/approval_contract.py`

## Risks / Caveats

- No execution code added.
- `evaluate_approval_satisfaction` is the canonical approval gate for Phase 3.2.

## Recommended Next Action for Receiver

1. Re-review cleanup against M1/M2/L1/L2/L3-L5 in `docs/REVIEW_CLAUDE_PHASE_3_1.md`.
2. If approved, merge cleanup branch and open **T-PHASE3-2-EXECUTOR**.