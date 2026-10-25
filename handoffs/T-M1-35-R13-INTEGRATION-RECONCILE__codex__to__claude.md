# Handoff: T-M1-35-R13-INTEGRATION-RECONCILE

**Handoff Protocol:** v2
**From:** codex
**To:** claude
**Date:** 2026-10-26
**Task Status After Handoff:** review

## What I Did

- Copied staged R12 JSON evidence unchanged into tests/fixtures/r12_e2e. Extracted original tool_call, usage, max_turns_reached and end events in order from the real Grok stream, retaining all 87 calls (including outside-worktree targets), 30 usage events and terminal events. Removed token/thought deltas and tool updates only. The tests read committed-path fixtures rather than ignored runtime evidence.
- Reworked continuation tests around a transient retry-eligible failed launch in a temporary fixture. Kept reserved ownership, competing holders, prior_run_ids, exactly-one-winner and stale-save fencing assertions. Kept retry-budget and notice-after-drain idempotence coverage.
- Tested immediate turn-budget reviewable_failure, retained terminal lock, no requeue and no dead-letter loop. The R12 saved max-turn result plus refused-launch evidence now asserts one actionable reviewable failure instead of continuation or refusal x3.
- Registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## What Remains

Claude must run tests.test_builder_isolation_contract.WindowsBoundaryTests under the intended supervisor token. The task contract explicitly excludes it from this sandbox run because CreateRestrictedToken fails with WinError 87. No OS boundary pass is claimed.

## Decisions Made

Product inconsistencies required scoped changes: failure_classify ignored the actual max_turns_reached event and still marked recognized max_turns retry-eligible; orphan recovery could preserve it for continuation; and saved R12 lock-owner evidence could trigger relaunch despite a newer refused attempt. Max-turn classification is now nonretryable, shared recovery normalization produces a terminal actionable failure, and legacy max-turn ownership is exhausted before any claim/launch. Removed the obsolete max-turn automatic continuation branch. Normal and fallback terminal diagnostics now include reviewer instructions and the existing diagnostic payload. Generic continuation preserves a worktree only for retry-eligible terminal states, retaining the existing ownership gate. The 30-turn default and transient classifications are unchanged.

## Open Questions

None for this reconciliation. The OS isolation proof remains a separate reviewer responsibility.

## How to Verify My Work

Use C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe and TEMP/TMP=%LOCALAPPDATA%/Temp/r13-t35, outside this clone.

- python -m unittest tests.test_retry_lock_continuation tests.test_builder_watch tests.test_builder_supervisor_contract tests.test_work_lock tests.test_prelaunch_failure_isolation tests.test_builder_condition_retry
- python -m unittest tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root
- python scripts/validate.py
- git diff --check

## Verification Results

- Required focused modules plus tests.test_failure_classify: 80 tests passed, TRUE exit 0, runtime/t35-verified-tests.txt and runtime/t35-verified-tests-exit.txt.
- Required five-module guard pack: 39 tests passed, TRUE exit 0, runtime/t35-guards.txt. PowerShell labels native stderr as NativeCommandError in the captured output; the process exit was 0 and unittest reported OK.
- Real-stream replay with the added classification assertion: 4 tests passed, TRUE exit 0, runtime/t35-stream-check.txt.
- Final strengthened continuation lineage/worktree and stream assertions: 16 tests passed, TRUE exit 0; runtime/t35-final-replay.txt and runtime/t35-final-replay-exit.txt.
- scripts/validate.py passed, TRUE exit 0, runtime/t35-validate-final.txt and runtime/t35-validate-final-exit.txt; revalidated after this handoff update. git diff --check passed, exit 0.
- Earlier failed development runs are retained: initial 68-test run had three fixture-setup errors (resume flag absent); the next had one retry-budget fixture failure (missing fingerprint); a 23-test regression run exposed the real max_turns_reached parsing bug plus that fixture failure; the next 80-test run retained only the parsing failure. Corrected both and reran to the passing results above. These earlier nonzero runs are not claimed as passes.

## Risks / Caveats

No commits or external actions were authorized or performed. This is an uncommitted implementation; empty commit-bound fields are intentional and no sealed full-suite or remote equality claim is made. No session pickup, real assignment/lock/claim operations, canonical checkout, live state or deploy-clone access occurred. Required tests use temporary stand-ins, as authorized by this task. Historical paths in fixtures are inert strings.

## Recommended Next Action for Receiver

Review the diff, run the excluded real OS boundary test, then commit and generate commit-bound full-suite evidence under the normal reviewer workflow.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/r13-integration
branch: agent/integration/R13
base_sha: 9756e44042022e73c8ddc9741de2f2e815f73570
implementation_sha:
tests_commit_sha:
final_head_sha: 9756e44042022e73c8ddc9741de2f2e815f73570
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 119
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-35-R13-INTEGRATION-RECONCILE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/r13-integration
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Existing signed runtime used; no installs authorized.
