# Handoff: T-M1-38-BUILDER-DISPATCH-PAUSE

**Handoff Protocol:** v2
**From:** codex
**To:** claude
**Date:** 2026-10-26
**Task Status After Handoff:** review

## What I Did

- Added persistent builder-dispatch control at `runtime/dispatch/layer_supervisor/control/builder_dispatch.json`. Dispatch requires a valid object with explicit `paused: false` and nonblank actor, reason and at fields. Missing state pauses without alerts; unreadable/corrupt state pauses with one durable deduplicated alert.
- Added audited `stop_supervisor.py --builder-dispatch pause|resume --actor X --reason Y`, reusing operator/control locks and audit intent/outcome records. Assigned builders receive exit 3 before any mutation.
- Gated builder ticks before retries/wakes, direct retry/continuation entries, fallback selection, the common process launcher, legacy local builder/worker and assignment-watcher entries. Propagated the state root into launch plans and acceptance subprocess plans. Claude reviewer launches remain available.
- Kept orphan recovery and the stuck-assignment sweep running while paused. Paused wakes remain byte-identical and no retry/dead-letter/requeue action occurs. Builder and layer status expose paused, since, actor and reason.
- Added disposable-fixture tests for corrupt/absent/unreadable state, audit/guard refusal, persistent state, low-level/legacy launch prevention, review consumption, r12 finalisation and notice deduplication, orphan finalisation, retry/continuation no-ops and resume on the next tick. Existing launch fixtures explicitly resume their temporary state roots.
- Registered this handoff in `POST_TEST_ALLOWLIST_EXACT`.

## Decisions Made

The addendum overrides the original absent-file behavior: no control state means paused. State is read from disk on each entry, so restart does not reset the pause. The layer supervisor may continue hosting its builder service; that service performs recovery/status work while builder payload dispatch is paused. Existing Claude failure-notice behavior is retained; a fake reviewer proves completed-assignment review events still resolve while paused.

## What Remains

Receiver review and commit. No commit, push, deployment, live-state change or real control operation was performed.

## Open Questions

None.

## How to Verify My Work

Use `C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe`, with TEMP/TMP outside this clone.

- `python -m unittest tests.test_builder_dispatch_pause tests.test_stuck_assignment_recovery tests.test_retry_lock_continuation tests.test_prelaunch_failure_isolation`
- `python -m unittest tests.test_stop_supervisor tests.test_layer_supervisor tests.test_launch_resilience tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root`
- `python scripts/validate.py`
- `git diff --check`

## Verification Results

Required combined suite: 116 tests passed, TRUE exit 0 (`dispatch-pause-focused-final.log`, `dispatch-pause-focused-final-exit.txt`). This runs new dispatch pause tests, stuck assignment recovery, retry lock continuation, prelaunch isolation, stop supervisor, layer supervisor and launch resilience.

Final builder/condition run: 55 tests passed, TRUE exit 0 (`dispatch-pause-builder-final.log`, `dispatch-pause-builder-final-exit.txt`), including the later same-assignment continuation case and the condition retry suite. Guard pack: 39 tests passed, TRUE exit 0 (`dispatch-pause-guards-final.log`, `dispatch-pause-guards-final-exit.txt`). These commands overlap; the combined current test inventory is 167 unique test cases.

Validator including this handoff passed, TRUE exit 0 (`dispatch-pause-handoff-validate.log`, `dispatch-pause-handoff-validate-exit.txt`); independent final validation also passed, TRUE exit 0 (`verification-root-validator-final.log`, `verification-root-validator-final.exit`). `git diff --check` passed, TRUE exit 0. Existing historical event-schema warnings remain.

Earlier checks exposed a missing os import in the resumed fixture and an overbroad cleared environment that removed executable lookup, plus incorrect mock targets and a notice-consumer expectation. These were corrected. Initial combined run: 146 tests, 29 errors, TRUE exit 1 (`dispatch-pause-verification.log`). Intermediate new-test run: 16 tests, 3 failures/2 errors, TRUE exit 1 (`dispatch-pause-new-final.log`). A separate attempted command could not open an already-held log and did not execute Python; no native exit code is claimed for it. The separate resumed run's earlier 107-test command returned TRUE exit 1 with 29 missing-import errors (`dispatch-pause-tests-v2.log`); the 13-test development check returned TRUE exit 1 with three test-harness failures (`dispatch-pause-new-v2.log`); the next 16-test check returned TRUE exit 1 with two mock-target errors (`dispatch-pause-new-v3.log`). All are superseded by the passing final runs above.

## Risks / Caveats

Independent continuation verification: final focused required run passed 55 tests, TRUE exit 0 (`verification-root-focused-0655.log`, `verification-root-focused-0655.exit`). The separate remaining-required run executed 101 tests with one failure, TRUE exit 1 (`verification-root-remaining-0651.log`, `verification-root-remaining-0651.exit`): `test_foreign_job_is_refused_and_decoy_survives` returned stop CLI exit 4 instead of expected 0. Its isolated rerun passed without code changes, TRUE exit 0 (`verification-root-stop-recheck-0656.log`, `verification-root-stop-recheck-0656.exit`). The cause was not established; transient stop timing under concurrent load is a possibility. The passing combined suite above and this failed batch are both retained as evidence. Independent validator passed, TRUE exit 0 (`verification-root-validator-0653.log`, `verification-root-validator-0653.exit`).

Another process was visibly editing this same working tree and writing test logs during continuation. It was not signaled or terminated; distinct verification log names were used. Review the final diff together with verification evidence. No access to the canonical checkout, deploy clones or live assignments/locks occurred. All control/assignment mutations used temporary test roots. Required existing stop/layer tests start and clean up their own disposable processes; new dispatch tests use fake launchers. No sealed full-suite or remote-equality claim is made.

## Recommended Next Action for Receiver

Review the local diff and evidence, then commit through the normal review workflow. Automatic live builder dispatch must remain disabled until the owner authorizes an audited resume after the remaining isolation/authentication checks pass.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-38-builder-dispatch-pause
branch: agent/codex/m1-38-builder-dispatch-pause
base_sha: 550868efdf7edcce3b0f37daf6656db817a187ea
implementation_sha:
tests_commit_sha:
final_head_sha: 550868efdf7edcce3b0f37daf6656db817a187ea
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 287
test_exit_code: 1
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-38-BUILDER-DISPATCH-PAUSE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-38-builder-dispatch-pause
known_exempt_failures: ["tests.test_builder_isolation_contract.WindowsBoundaryTests.test_real_adversarial_builder_and_descendants"]
dependency_install: skipped
dependency_install_reason: Existing signed runtime used; no dependency installation required.

## T-M1-38B

Reviewer finding addressed with test-fixture changes only. Added `tests/_dispatch_fixture.py:resume_builder_dispatch`, which invokes the existing audited `builder_dispatch(..., 'resume', ...)` helper against each disposable fixture root and asserts success. The temporary environment patch clears only the builder-run guard for this fixture control operation and restores it immediately.

Updated the physical-launcher fixture and its standalone launch root, the condition-retry fixture (replacing its inline resume), watcher wake fixtures, quota retry fixtures, legacy local-builder fixtures, local-builder/worker deadline fixtures, launcher environment fixture, and isolation contract fixtures (including the separate builder workspace). Inheriting supervisor, continuation, work-lock, streaming, capacity, prelaunch and write-contention tests receive the same explicit opt-in. Existing paused, missing-state, corrupt-state and restart tests retain their deliberate paused setup. No product behavior or assertions were changed in T-M1-38B.

Audit searched every Python test module for `launch_process`, `process_once`, `process_wake_signal`, `reevaluate_blocked_builders`, `run_local_builder`, `run_adapter_local_builder`, `run_local_builder_worker`, `watch_assignments`, `launch_isolated`, `_launch_agent_process`, and `local_builder_core`, with an additional search for composer/codex legacy builder references. Remaining matches cover inherited launch fixtures, pause tests, reviewer/consumer paths, recovery-only sweeps, config/planning, or source inspection; those do not need a separate builder launch opt-in.

The broad run exposed four additional worker/core launch tests in `WorkLockTests`; their temporary root now also resumes through the shared helper. The quota ledger fixture creates its already-present parent with `exist_ok=True`, since audited resume creates `runtime/dispatch` first. Assertions remain unchanged.

Verification uses `C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe` and TEMP/TMP at the system temporary directory outside this clone. TRUE native exit codes are stored separately from PowerShell's stderr formatting:

- Physical launcher: `-m unittest tests.test_physical_agent_launcher`: 18 tests, exit 0 (`dispatch-pause-38b-physical.log`, `.exit`).
- Broad regression: 287 tests, exit 1 (`dispatch-pause-38b-tests.log`, `.exit`); initially five failures and one error. Command: `-m unittest tests.test_physical_agent_launcher tests.test_agent_wake_poke tests.test_builder_condition_retry tests.test_builder_isolation_contract tests.test_builder_supervisor_contract tests.test_capacity_leak tests.test_config_root tests.test_dispatch_executor tests.test_grok_streaming tests.test_phase3_7c_local_builder tests.test_prelaunch_failure_isolation tests.test_provenance_deploy_root tests.test_quota_probe tests.test_retry_lock_continuation tests.test_run_deadlines tests.test_stuck_assignment_recovery tests.test_windows_write_contention tests.test_work_lock tests.test_builder_dispatch_pause tests.test_import_guard tests.test_console_encoding tests.test_process_ownership_fencing`. This includes every changed test module, the pause suite and the complete five-module guard pack.
- After correcting the work-lock and quota fixtures: `-m unittest tests.test_work_lock tests.test_quota_probe`: all 43 tests pass, exit 0 (`dispatch-pause-38b-corrected.log`, `.exit`). These results supersede the four work-lock failures and quota setup error in the broad run. Other fixture modules and guard cases passed in that run.
- `scripts/validate.py` before handoff update: exit 0 (`dispatch-pause-38b-validate.log`, `.exit`).

One failure remains outside this fixture-only follow-up: `tests.test_builder_isolation_contract.WindowsBoundaryTests.test_real_adversarial_builder_and_descendants` reaches the resumed launcher, but Windows restricted-token creation refuses with `WinError 87: The parameter is incorrect`. Its assertion was retained and product isolation code was not modified. The Repository Verification block records the 287 unique cases exercised and nonzero overall status; its `known_exempt_failures` lists this unresolved failure for schema validity, not owner approval or an isolation waiver. No all-green claim is made.

No repository commit, push, deployment, real assignment/lock/claim mutation, or live dispatch resume was performed. All dispatch control writes were to disposable test roots. The earlier T-M1-38 verification narrative is retained as historical evidence; this section records the T-M1-38B outcome.

Final checks: `scripts/validate.py` with this T-M1-38B section and updated Repository Verification fields passes, TRUE exit 0 (`dispatch-pause-38b-final-validate.log`, `.exit`). `git diff --check` passes, TRUE exit 0 (`dispatch-pause-38b-diff-check.log`, `.exit`). Existing deprecated event-schema warnings remain. Receiver should review the fixture diff and retain the isolation failure as an outstanding gate before any live dispatch resume.
