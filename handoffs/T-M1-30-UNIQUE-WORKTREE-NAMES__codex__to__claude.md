# Handoff: T-M1-30-UNIQUE-WORKTREE-NAMES

**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

Replaced truncated run names with a stable 24-hex-character SHA-256 digest of the full validated run id (96 bits). Allocations check existing branches, directories and active allocation records and choose a fresh identity on collision, with at most eight candidates. Git-add races also retry within that budget. Existing evidence is never deleted, reset or reused. Registry records retain the original run id and chosen branch/path; existing run-state recording is unchanged.

Added regressions for same-window runs, legacy branches, full-id suffix sensitivity, existing candidate branches/directories, concurrent branch claims, bounded exhaustion, and long task paths. Existing duplicate same-run allocation blocking and condition-retry continuation remain unchanged.

## What Remains

Receiver review, commit, and commit-bound verification in a Git-writable session.

## Decisions Made

Path budget is 199 characters: absolute configured root + two separators + task component (at most 60, reduced to the available budget) + 24-character run digest. An overlong configured root fails explicitly if it leaves no room for the task component. Branch names remain within 120 characters. Collision candidates hash the original run id plus fresh UUID entropy; their allocation records still identify the original run. Same-run continuation uses the existing preserved-worktree route without deriving a new name.

## Open Questions

None.

## How to Verify My Work

All 117 working-tree impacted tests passed (progress.txt). The runner was stopped after completing these tests, when it reached the already completed dispatch-executor suite. Combined distinct coverage is 150 tests: 148 passed, two Application Control errors. Completed focused runs: 15 allocator tests passed (allocator-final.txt); the earlier allocator/condition-retry run passed 23 tests (focused.txt), including all 11 condition-retry tests. Import guard passed (1 test, 38.584 seconds, import-final.txt). Required dispatch/console/ownership/provenance run completed 38 tests: 36 passed, two environment errors (nonimport.txt). Windows Application Control refused Python child creation with WinError 4551 in tests.test_console_encoding.ConsoleEncodingTests.test_list_tasks_cp1252 and tests.test_process_ownership_fencing.ProcessOwnershipTests.test_real_grandchild_terminated. These are recorded failures, not exemptions. validate.py passed with exit 0 before final result annotations (validate-final.txt); the final closeout attempt could not start Python because of Windows Application Control. The validator_exit_code below records the completed earlier run. git diff --check passed.

Evidence and sandbox-compatible runner: runtime/dispatch/m1-30/. The runner changes only directory mode 0700 to inherited ACL mode 0777; assertions and Git behavior are unchanged.

```powershell
python scripts/impacted_tests.py --base b4aee5f
python runtime/dispatch/m1-30/run_offline.py tests.test_phase3_4_worktree_allocator tests.test_builder_condition_retry
python runtime/dispatch/m1-30/run_offline.py tests.test_achievable_evidence_seal tests.test_config_root tests.test_phase3_3_review_fixes tests.test_phase3_4_1_integrity_closeout tests.test_phase3_4_worktree_allocator tests.test_prelaunch_failure_isolation tests.test_provenance_deploy_root tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing
python scripts/validate.py
git diff --check
```

The requested committed-range selector returned no modules because HEAD equals base. Also selected and ran direct dependents of the working-tree changes using scripts.impacted_tests.impacted_tests.

## Risks / Caveats

Two required subprocess tests are blocked by Windows Application Control; rerun those where their child processes are permitted. Stock tempfile setup failed with Windows sandbox ACL errors; reruns use inherited directory ACLs. Git metadata is read-only, so SHA fields identify base HEAD rather than a committed implementation. remote_head_sha is an offline placeholder; no remote was queried. Regenerate commit-bound evidence after review/commit. No network, canonical checkout command, pickup, push, merge or dependency installation was performed. Dependencies are unchanged.

## Recommended Next Action for Receiver

Review changes, commit, and regenerate commit-bound verification.

## Reviewer note (Claude, R12 closeout, 2026-10-23)

The builder's recorded `test_exit_code: 1` is kept as truthful evidence. The two non-passing tests listed in `known_exempt_failures` were blocked by Windows Application Control (WinError 4551) in the builder environment, not failed by the change. Claude re-ran them on the PSF-signed CPython 3.11.9 runtime: `tests.test_phase3_4_worktree_allocator tests.test_builder_condition_retry tests.test_console_encoding tests.test_process_ownership_fencing`, 40 tests OK, true exit 0. Commit-bound evidence for R12 is the full-suite artifact on the R12 final SHA.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-30-branchnames
branch: agent/codex/T-M1-30-UNIQUE-WORKTREE-NAMES
base_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
implementation_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
tests_commit_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
final_head_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
remote_head_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
git_status_clean: false
validator_commit_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
test_count: 150
test_exit_code: 1
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-30-UNIQUE-WORKTREE-NAMES__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-30-branchnames
known_exempt_failures: ["tests.test_console_encoding.ConsoleEncodingTests.test_list_tasks_cp1252", "tests.test_process_ownership_fencing.ProcessOwnershipTests.test_real_grandchild_terminated"]
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies unchanged
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-30-branchnames

