# Handoff: T-PHASE3-4-WORKTREE-APPROVAL-MVP — Phase 3.4 Worktree + Approval Authenticity MVP
**From:** composer
**To:** claude
**Date:** 2026-06-20T16:55:00Z
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did

- Implemented operator-commanded Git worktree allocator (`dispatch/worktree_allocator.py`, CLIs).
- Implemented HMAC-SHA256 signed approvals (`dispatch/approval_signing.py`, sign/verify CLIs).
- Implemented single-use approval anti-replay (`dispatch/approval_replay.py`).
- Integrated worktree + signed approval + replay into `execution_gate.py` and `executor.py`.
- Added 27 Phase 3.4 tests (333 total); extended event vocabulary; ADRs 0025–0028.

## What Remains

- Claude final review of Phase 3.4.
- Phase 3.5 (not started).

## Decisions Made

- Worktree root defaults to sibling `<repo-parent>/<repo-name>-worktrees/`; override via `AGENTIC_OS_WORKTREE_ROOT`.
- HMAC proves local key possession, not legal identity.
- Approval claim is conservative: failed execution still consumes approval.
- Dirty worktree cleanup refused (`preserved` status); branches preserved after remove.
- Only `local-python-exec-test` remains executable.

## Open Questions

None.

## How to Verify My Work

```bash
cd C:/Users/gabot/agentic-os
git fetch origin
git checkout agent/composer/T-PHASE3-4-WORKTREE-APPROVAL-MVP
python scripts/run_tests.py
python scripts/validate.py
python -m unittest tests.test_phase3_4_safety_boundaries -v
python scripts/verify_repository_verification.py handoffs/T-PHASE3-4-WORKTREE-APPROVAL-MVP__composer__to__claude.md
git diff ecec7669c523ad498dc6697875e3a7d724abe78d..HEAD --name-only
```

## Worktree Allocator

- CLI: `scripts/allocate_worktree.py`, `inspect_worktree.py`, `cleanup_worktree.py`
- Records: `runtime/worktrees/allocations/<allocation_id>.json`
- Git argv-only, no shell, allowlisted subcommands only.

## Approval Authenticity

- Env keys: `AGENTIC_OS_REVIEWER_APPROVAL_KEY`, `AGENTIC_OS_HUMAN_APPROVAL_KEY`
- CLI: `scripts/sign_approval.py`, `scripts/verify_approval.py`
- Signed record version 2 with canonical JSON HMAC-SHA256.

## Anti-Replay

- Claims: `runtime/dispatch/approval_consumed/<approval_id>.json`
- Atomic exclusive create; dry-run and verify do not consume.

## Executor Integration

- File-writing execution requires allocation record; no auto-allocation.
- Gate order: freshness → worktree → approval shape → signature → satisfaction → replay check → claim → subprocess.

## Tests and Validator

- **333** tests, exit **0** at `implementation_sha` `ecec7669c523ad498dc6697875e3a7d724abe78d`.
- Validator exit **0** at implementation commit.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-4-WORKTREE-APPROVAL-MVP
base_sha: deca7170bd5ee77e04b8a6ec2afe781ebd74cb35
implementation_sha: ecec7669c523ad498dc6697875e3a7d724abe78d
tests_commit_sha: ecec7669c523ad498dc6697875e3a7d724abe78d
final_head_sha: 1a299de3ebbda9530020295d4c1b80e3212b354b
remote_head_sha: 1a299de3ebbda9530020295d4c1b80e3212b354b
git_status_clean: false
validator_commit_sha: ecec7669c523ad498dc6697875e3a7d724abe78d
test_count: 333
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: docs-only-allowlist-v2
post_test_files: runtime/unittest_last_run.txt, decisions/ADR-0025-worktree-allocator-mvp.md, decisions/ADR-0026-hmac-approval-authenticity.md, decisions/ADR-0027-single-use-approval-anti-replay.md, decisions/ADR-0028-phase-3-4-execution-boundary.md, decisions/INDEX.md, docs/PHASE_3_4_APPROVAL_AUTHENTICITY.md, docs/PHASE_3_4_BASELINE.md, docs/PHASE_3_4_EXECUTOR_INTEGRATION.md, docs/PHASE_3_4_HARDENING_REPORT.md, docs/PHASE_3_4_REVIEW_PACKET.md, docs/PHASE_3_4_WORKTREE_ALLOCATOR.md, docs/REVIEW_COMPOSER_PHASE_3_4_SELF_REVIEW.md, tasks/active/T-PHASE3-4-WORKTREE-APPROVAL-MVP.yaml
working_copy_path: C:/Users/gabot/agentic-os

## Post-Test Diff

Only allowlisted documentation/handoff/task paths after `tests_commit_sha`.

## Safety Boundaries

- Only `local-python-exec-test` has `supports_execution: true`.
- Subprocess: `dispatch/executor.py` (agent execution) + `dispatch/worktree_allocator.py` (git only).
- No scheduler, MCP execution, dashboard execution controls, or real-agent activation.

## Risks / Caveats

- No OS keyring integration; keys are env-only.
- No key rotation service.
- `final_head_sha` records parent tip before handoff commit (self-reference limit).
- Untracked local scratch files under `runtime/` may remain.

## Recommended Next Action for Receiver

Run full verification at branch tip. If green, APPROVE Phase 3.4. Do not start Phase 3.5 implementation.