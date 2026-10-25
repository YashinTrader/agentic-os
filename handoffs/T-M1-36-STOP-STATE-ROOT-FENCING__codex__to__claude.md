# Handoff: T-M1-36-STOP-STATE-ROOT-FENCING

**Handoff Protocol:** v2
**From:** codex
**To:** claude
**Date:** 2026-10-26
**Task Status After Handoff:** review

## What I Did

- Added read-only inspection of each recorded live PID's command line, expected supervisor/layer entrypoint and resolved state root, alongside the existing OS process creation identity check. Explicit --state-root (both syntaxes) takes precedence over AGENTIC_OS_STATE_ROOT; relative paths resolve against the process cwd and comparisons ignore case.
- Stop verifies the recorded root and all current/historical children before publishing a graceful request, during polling, and immediately before forced termination. Foreign or missing ownership evidence returns audited exit 4. Existing Job membership, creation-time, process-group and graceful acknowledgement fences remain.
- Startup ignores a demonstrably foreign recorded root rather than adopting or blocking on it; inaccessible or missing root evidence conservatively blocks startup. The run_supervisor_layers entrypoint delegates its instance check here. Existing process_ownership termination uses retained handles for task-launched processes, not reconstructed status ownership, and remains unchanged. No packaging uninstall implementation was found in this checkout.
- Added real test-owned subprocess regressions for copied status, foreign recorded children, and independent startup against copied status. Updated test hosts to expose actual expected entrypoints/state-root arguments. Added environment, relative path, case normalization and missing evidence checks.
- Added this handoff to POST_TEST_ALLOWLIST_EXACT.

## What Remains

- Reviewer inspection and commit; the contract prohibits builder commits.

## Decisions Made

- A process snapshot alone is insufficient authority: process creation identity is rechecked after inspecting the PID. Forced Windows termination retains the existing process handle and verifies Job membership; POSIX retains process-group fences.
- Missing/unreadable ownership evidence cannot authorize stopping or startup adoption. A proven foreign entrypoint/root does not block an independent root.

## Open Questions

- None.

## How to Verify My Work

Use C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe, with TEMP/TMP outside the clone.

- python -m unittest tests.test_stop_supervisor tests.test_layer_supervisor tests.test_launch_resilience tests.test_process_ownership_fencing tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_provenance_deploy_root
- python scripts/validate.py
- git diff --check

## Verification Results

- Final combined focused modules and five-module guard pack (shared ownership module run once): 101 tests passed in 191.369 seconds, TRUE exit 0. Evidence: runtime/t36-final-tests.txt and runtime/t36-final-tests-exit.txt.
- Initial focused run: 71 tests passed, TRUE exit 0; initial guard pack: 39 tests passed, TRUE exit 0. Final run includes the two subsequently added tests and final conservative startup handling.
- scripts/validate.py: passed, TRUE exit 0; final evidence runtime/t36-final-validate.txt and runtime/t36-final-validate-exit.txt. Existing deprecated event warnings remain.
- git diff --check: passed, exit 0.

## Risks / Caveats

- No commits, pushes, session pickup, assignment operations or external actions performed. All signalled processes were test-owned subprocesses. No canonical checkout, live state or deploy clone was accessed. Required tests use temporary fixtures outside this clone.
- psutil must be available for ownership inspection; missing dependency fails closed. Existing signed runtime supplied it; no dependency installation was needed.
- This is an uncommitted change. Commit-bound and remote verification fields remain empty intentionally; no full-suite seal is claimed.

## Recommended Next Action for Receiver

Review the ownership fencing and regression evidence, then commit under the normal reviewer workflow.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-36-stop-root-fencing
branch: agent/codex/m1-36-stop-root-fencing
base_sha: be788a4b4132b57dab9d9bb1e0c4560c4cc82a6e
implementation_sha:
tests_commit_sha:
final_head_sha: be788a4b4132b57dab9d9bb1e0c4560c4cc82a6e
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 101
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-36-STOP-STATE-ROOT-FENCING__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-36-stop-root-fencing
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Existing signed runtime used; no installs authorized.
