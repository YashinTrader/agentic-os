# Handoff: T-M1-31-PROVENANCE-GIT-TIMEOUT
**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review (working-tree delivery)
**Handoff Protocol:** v2

> Reviewer note (Claude, R12 closeout): the builder's run was interrupted when the session ended, so the original handoff was left in a non-v2 draft format. Claude restructured it into the required v2 sections without changing its substance, and added the reviewer's independent verification below.

## What I Did
- `root_paths.py`:
  - Named 30-second Git timeout, with one retry on timeout (at most two attempts).
  - Non-fatal failure reasons recorded in `config_root_git_sha_error`.
  - Process-local, success-only cache keyed by the resolved config root.
  - Success metadata keeps its existing shape.
  - A reason is retained for each failure: missing `.git`, missing Git, nonzero Git status (first stderr line), persistent timeout, empty output, and other subprocess errors.
- `tests/test_root_paths_provenance.py`: seven regressions covering retry, persistent timeout with no failure caching, missing Git, per-root success caching, nonzero return and recovery, missing `.git`, and empty output.
- `scripts/repository_verification.py`: registered this exact handoff in `POST_TEST_ALLOWLIST_EXACT`.

## What Remains
Receiver review and commit, then commit-bound evidence through the release gate.

## Decisions Made
- Failures are never cached, so a transient timeout cannot hide a later success.
- The success path keeps the existing status shape. The error key appears only when the SHA cannot be determined.

## Open Questions
None.

## How to Verify My Work
All task Python used `C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe`. No dependencies were installed.

**Builder runs:**
- `-m unittest tests.test_root_paths_provenance tests.test_config_root tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root`: **53 tests OK, true exit 0**, 634 s.
- `scripts/impacted_tests.py --base b4aee5f`: exit 0, no modules selected because the changes were uncommitted.
- `git diff --check`: exit 0.

**Reviewer re-run (Claude):**
- `-m unittest tests.test_root_paths_provenance tests.test_config_root tests.test_provenance_deploy_root`: 31 tests OK, true exit 0, 15 s.

## Risks / Caveats
- Before reading TASK_INSTRUCTIONS.md, the builder followed the repository's session-start rule and attempted a session pickup against the canonical checkout using the default interpreter.
  - It failed with exit 1 (PermissionError creating an assignment claim) and claimed no assignment.
  - The reviewer verified no live writes by an mtime scan.
- Setup errors that are not passing results:
  - Two initial quoted cmd.exe launches exited 1 before running Python.
  - A run of the nonexistent module `tests.test_repository_verification` exited 1.
  - A read-only process inventory was denied by the sandbox.

## Recommended Next Action for Receiver
Integrate in R12 together with T-M1-30 and T-M1-32, then run the full suite on the final SHA.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-31-provenance-timeout
branch: agent/codex/m1-31-provenance-timeout
base_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
implementation_sha:
tests_commit_sha:
final_head_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 53
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-31-PROVENANCE-GIT-TIMEOUT__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-31-provenance-timeout
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; vendored dependencies in the signed runtime used
