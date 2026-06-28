# Phase 3.1 Review Packet — Controlled Executor Design

**Task:** T-PHASE3-1-DESIGN  
**Branch:** `agent/composer/T-PHASE3-1-DESIGN`  
**Mode:** Design only — no execution

## Summary for Claude

Phase 3.1 defines contracts Phase 3.2 can implement: executor request validation, approval
records bound to preview hashes, CLI inventory gate, worktree policy for file-writing
adapters, runtime capture layout, and KEY=VALUE allowlist extension in preview validation.

## Deliverables checklist

| Item | Path | Status |
|------|------|--------|
| Executor design | `docs/PHASE_3_1_EXECUTOR_DESIGN.md` | ✅ |
| Approval model | `docs/PHASE_3_1_APPROVAL_MODEL.md` | ✅ |
| Worktree strategy | `docs/PHASE_3_1_WORKTREE_SANDBOX_STRATEGY.md` | ✅ |
| Runtime capture | `docs/PHASE_3_1_RUNTIME_CAPTURE_CONTRACT.md` | ✅ |
| Executor contract | `dispatch/executor_contract.py` | ✅ |
| Approval contract | `dispatch/approval_contract.py` | ✅ |
| Freshness | `dispatch/freshness.py` | ✅ |
| ADR-0014 | `decisions/ADR-0014-*.md` | ✅ |
| ADR-0015 | `decisions/ADR-0015-*.md` | ✅ |
| ADR-0016 | `decisions/ADR-0016-*.md` | ✅ |
| Schemas | `schemas/*.schema.json` | ✅ |
| Tests | `tests/test_phase3_1_*.py` | ✅ |
| Self-review | `docs/REVIEW_COMPOSER_PHASE_3_1_DESIGN_SELF_REVIEW.md` | ✅ |

## Safety assertions

- No `subprocess` in `dispatch/executor_contract.py`, `approval_contract.py`, `freshness.py`
- `PHASE_3_2_EXECUTION_EVENT_TYPES` reserved, not in `ALLOWED_EVENT_TYPES`
- No dashboard execute/approve buttons added
- No task YAML mutation automation

## Verification commands

```bash
python scripts/run_tests.py
python scripts/validate.py
rg "subprocess" dispatch/executor_contract.py dispatch/approval_contract.py dispatch/freshness.py
python -m unittest tests.test_phase3_1_freshness.FreshnessTests.test_execution_events_not_in_allowed_yet -v
```

## Recommended Claude review focus

1. ADR-0014/0015/0016 acceptance for Phase 3.2 implementation gate
2. Preview hash field set completeness
3. KEY=VALUE policy vs adapter registry evolution (`forbidden_keys` future field?)
4. CLI inventory gate behavior when inventory file missing
5. Worktree policy for `codex-cli-preview` (`writes_files: true`, `repo_root` policy)

## Phase 3.2 blockers (explicit)

- Separate implementation task after ADR sign-off
- Approval recording UI/workflow (human operator)
- Git worktree allocator
- Subprocess executor with timeout and log capture
- Event emitters for `PHASE_3_2_EXECUTION_EVENT_TYPES`