# Handoff: T-M1-04-CHILD-SUPERVISION
**From:** codex
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** review (uncommitted implementation)
**Handoff Protocol:** v2

## What I Did

- Replaced fail-together layer launching with independent supervision and 2-second exponential restart backoff, capped at 300 seconds.
- Added a per-child breaker after more than five exits in 600 seconds. Its open state survives parent restart, and its sibling continues running.
- Added atomic status snapshots, the last 20 exit records per child, timestamps, exit codes, and bounded stderr tails. Continuous pipe draining prevents stderr backpressure.
- Added cooperative heartbeat ticks to idle loops and active process monitors, plus distinct progress markers for claims, launches, and work transitions. Stale or absent heartbeats trigger hung classification and restart after a minimum 60-second grace period.
- Added replacement launch counts, restart timestamps, and exit-to-replacement-heartbeat recovery timing. Launch tokens distinguish heartbeat generations and support Windows Python wrappers whose PID differs from the interpreter PID.
- Added graceful signal handling and active work-process cleanup; requested parent shutdown records stopped without appending a crash.
- Preserved claim, lease, poke archival, and M1-02 deferred reevaluation behavior; their focused regression tests pass.
- Documented operation in docs/LAYER_SUPERVISION.md and registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## What Remains

- Commit normally from a Git-writable environment. Git staging failed with permission denied creating .git/index.lock; no implementation commit exists.
- Regenerate commit-bound verification evidence after committing and rerun the closeout gate. The working-tree test result below is not committed-tip verification.
- The receiver owns any broader suite run; this session did not run full discovery.

## Decisions Made

- Heartbeats are emitted by actual work and polling loops, not an unconditional background timer. Waiting for an active agent counts as ticking without inventing progress.
- Measure recovery only after observing the replacement heartbeat; include restart backoff in recovery_seconds.
- Bound the stderr pipe buffer to 8192 bytes and each persisted stderr tail to 8192 characters. Retain at most 20 exits per child.
- Preserve crash-loop state across parent restarts and require an operator to retain the audit and reset status after fixing the cause.
- Leave Task Scheduler, adapter enablement, credentials, and external resources unchanged.

## Open Questions

- None blocking the implementation review. Service-level recovery after an uncatchable parent kill remains outside this task's system-configuration boundary.

## How to Verify My Work

```powershell
python -m unittest -v tests.test_layer_supervisor tests.test_claude_event_consumer tests.test_physical_agent_launcher tests.test_claude_reviewer_adapter tests.test_phase3_3_review_fixes.HandoffVerificationProtocolTests
python scripts/validate.py
git diff --check
python scripts/handoff_closeout_gate.py handoffs/T-M1-04-CHILD-SUPERVISION__codex__to__claude.md
```

## Verification Results

- Final focused run: 91 tests, 0 failures, 0 errors, 35.511 seconds, exit 0. This includes 16 supervision/heartbeat tests and the required physical-agent launcher module. All agent CLIs are mocked; the real crash test uses only a tiny sys.executable Python child exiting 17, then a replacement heartbeat.
- Final focused output: runtime/dispatch/m1-04/focused-tests.txt; summary: runtime/dispatch/m1-04/summary.json.
- Sandbox fixture setup: ordinary tempfile directories were unreadable due to Windows mode-0700 ACL behavior. The successful run redirected all mkdtemp calls (including existing tests hardcoding C:/tmp) into runtime/dispatch/m1-04/tmp and used inherited permissions for those test directories only. The local runner is runtime/dispatch/m1-04/run_focused.py, invoked with python -c "exec(open('runtime/dispatch/m1-04/run_focused.py').read())". Production permissions and code were not patched for tests.
- Earlier runs failed at temporary-directory access, exposed the wrapper-PID mismatch subsequently fixed with launch tokens, or were interrupted during existing test fixture setup. They are not represented as passing.
- Ten changed Python modules/test files compiled successfully, exit 0.
- git diff --check: exit 0.
- python scripts/validate.py: exit 0, with pre-existing deprecated event warnings.
- Git staging: exit 1, permission denied creating .git/index.lock. No push, merge, or network action was attempted.
- Closeout gate: exit 1. The existing unittest artifact belongs to a different commit/repository and has a different test count; it was deliberately not rewritten to imply a committed full-suite run. Validator checks inside the gate passed, exit 0. Details: runtime/dispatch/m1-04/closeout.txt. Committed-tip verification remains outstanding.

## Risks / Caveats

- Changes are uncommitted because .git is read-only in this sandbox. No dependency audit was run: external network is forbidden and no commit was possible.
- The successful focused run used the described fixture-only temporary-directory workaround. Rerun normally on the receiver's host.
- Uncatchable Windows force termination or power loss cannot run a Python shutdown handler. Catchable signals and CTRL_BREAK are handled; existing atomic evidence survives abrupt termination.
- Automatic approval review rejected recursive temporary-directory cleanup as blocked by policy. Temporary test artifacts remain locally under runtime, including directories from interrupted fixture setup. They are not implementation files.
- Existing untracked TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log were preserved.
- The SHA fields below identify the unchanged checkout HEAD during working-tree verification. They do not claim the implementation has been committed. remote_head_sha is the locally recorded origin/HEAD (the M1-02 base); no remote tracking ref exists for this task branch and no push is claimed.

## Recommended Next Action for Receiver

Review the working diff and focused test evidence. In a Git-writable environment, commit the scoped changes, rerun focused checks, regenerate the v2 verification block at the committed tip, and run the closeout gate. Perform broader integration testing separately.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-04-clone
branch: agent/codex/T-M1-04-CHILD-SUPERVISION
base_sha: 8f7ff19986c818b38c1bddd7cf97930f26d56990
implementation_sha: 8f7ff19986c818b38c1bddd7cf97930f26d56990
tests_commit_sha: 8f7ff19986c818b38c1bddd7cf97930f26d56990
final_head_sha: 8f7ff19986c818b38c1bddd7cf97930f26d56990
remote_head_sha: 8f7ff19986c818b38c1bddd7cf97930f26d56990
git_status_clean: false
validator_commit_sha: 8f7ff19986c818b38c1bddd7cf97930f26d56990
test_count: 91 focused tests (working tree; not the full suite)
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-04-CHILD-SUPERVISION__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-04-clone
