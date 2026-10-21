# Handoff: T-M1-04B-THREE-DEADLINES
**From:** codex
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** review (uncommitted implementation)
**Handoff Protocol:** v2

## What I Did

- Added a shared monotonic three-deadline model for builder and reviewer processes. Startup expiry is failed_launch, inactivity expiry is stalled, and the overall cap is timed_out even with continuing activity.
- Added per-adapter startup/inactivity configuration in agents/run_deadlines.yaml: reviewers 90/300 seconds, builders 180/600 seconds. Overall limits use the launch timeout.
- Incrementally parse genuine structured agent events. Thread/session initialization, arbitrary stdout, supervisor heartbeats, and process liveness do not count as activity. Malformed event fields are ignored.
- Compare builder worktree mtimes/sizes against a prelaunch snapshot. Exclude runtime/control artifacts, captured logs, dependency/cache directories, .git, and symlinks. Reviews use structured stdout activity only.
- Persist startup_activity_at, last_activity_at, activity_events, deadline_fired, and deadline_fired_at atomically in run records, including evidence before process termination.
- Put the production Codex/composer local-builder path through the same streaming monitor. Preserve its filtered environment. Replace blocking prompt pipe writes with file-backed stdin.
- Retain work locks/worktrees, prevent a startup deadline from launching another adapter, and route each deadline failure through one terminal poke. Preserve reviewer failure classification in the event consumer and its existing deferral/backoff behavior.
- Added fake-process/injected-clock tests covering startup, inactivity, active long runs, overall timeout, heartbeat exclusion, worktree writes, durable evidence, retained locks, terminal pokes, launch errors, worker routing, malformed stream events, stdin, and environment filtering.
- Excluded runtime artifacts from local-builder test fixture copies so a fixture located inside this clone cannot recursively copy itself.
- Documented operation in docs/RUN_DEADLINES.md and registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## What Remains

- Commit from a Git-writable environment. Staging failed creating .git/index.lock with Permission denied; nothing is staged and no implementation commit exists.
- Regenerate commit-bound verification evidence after committing. The checks here apply to the working tree, not a committed implementation or published branch.
- The receiver owns broader integration testing; no full test suite was run.

## Decisions Made

- Use monotonic duration checks and UTC evidence timestamps. Activity refreshes only the inactivity timer, never the overall cap.
- Persist the specific deadline failure rather than temporarily overwriting it with generic reviewer cancellation.
- Keep existing synchronous subprocess_runner and skip-agent test seams; production uses streaming Popen monitoring. New tests exercise the production local-builder branch through fake Popen processes.
- Assigned local-builder failures route in the worker; unassigned direct runs emit their own failure poke, avoiding duplicate terminal notifications.
- Preserve adapter identities, execution gates, reviewer read-only restrictions, logical work ownership, and external action boundaries.

## Open Questions

- None blocking code review. The work is intentionally uncommitted because Git metadata is read-only in this environment.

## How to Verify My Work

```powershell
python -m unittest -v tests.test_run_deadlines tests.test_work_lock tests.test_layer_supervisor tests.test_claude_event_consumer tests.test_physical_agent_launcher tests.test_claude_reviewer_adapter tests.test_phase3_7c_local_builder tests.test_phase3_3_review_fixes.HandoffVerificationProtocolTests
python scripts/validate.py
git diff --check
```

For this sandbox, use the retained fixture runner runtime/dispatch/m1-04b/run_focused.py. It redirects temporary fixtures into this clone, creates directories with inherited permissions, and retains them for inspection. It does not change production behavior or global configuration. Normal unittest invocation initially hit temporary-directory access errors and was interrupted; interrupted runs are not counted as passing.

## Verification Results

- Focused regression run: 157 tests, zero failures/errors, exit 0, 493.578 seconds. Output: runtime/dispatch/m1-04b/focused-tests.txt; summary: runtime/dispatch/m1-04b/summary.json.
- Final affected-module run: 80 tests, zero failures/errors, exit 0, 33.672 seconds. Includes all 22 new tests plus physical launcher, reviewer adapter, and handoff protocol tests. Output: runtime/dispatch/m1-04b/final-affected-tests.txt; summary: runtime/dispatch/m1-04b/final-affected-summary.json.
- The final affected run followed the environment-filtering fix, malformed-event guards, and reviewer launch-error poke fix. The earlier regression run supplies the unaffected lock, layer supervisor, event consumer, and local-builder regression coverage.
- python scripts/validate.py: exit 0 after handoff creation; only pre-existing deprecated-event warnings. Final captured output: runtime/dispatch/m1-04b/validate.txt.
- git diff --check: exit 0.
- git add -- orchestrator/run_deadlines.py: exit 1, unable to create .git/index.lock (Permission denied).
- No session pickup, unittest discovery, full test suite, push, merge, deployment, external network call, credential change, or remote agent dispatch was performed.

## Risks / Caveats

- Polling defaults to two seconds, so deadline detection follows that cadence. Long silent tools need an appropriate per-adapter inactivity budget; steady genuine activity is explicitly tested beyond both startup and inactivity windows.
- Runtime/caches/dependency files are deliberately excluded from worktree activity so control-plane writes cannot mask a stall. Read-only agents must emit structured activity.
- Agent CLIs are faked in the new tests. Termination follows the existing process-handle kill/wait behavior; live Windows CLI wrappers were not exercised.
- Test temporary artifacts remain inside runtime/dispatch/m1-04b/tmp. Initial default-temp access failures and interrupted preliminary runs are not passing verification evidence.
- No dependency changes were made. No network dependency audit was run: external network was forbidden and Git staging was blocked.
- Existing untracked TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log were preserved.
- The SHA fields below identify the unchanged checkout HEAD during working-tree testing. They do not claim these changes are committed. remote_head_sha is the locally recorded origin/HEAD, not a fetched or pushed task branch. Committed-tip closeout verification remains outstanding; no unrelated full-suite artifact was rewritten to imply success.

## Recommended Next Action for Receiver

Review the working diff and focused test artifacts. Commit the scoped implementation in a Git-writable environment, rerun focused checks, regenerate the v2 commit-bound verification evidence, and perform the closeout gate. Broader integration testing is separate.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-04b-clone
branch: agent/codex/T-M1-04B-THREE-DEADLINES
base_sha: fa8ca1b1988d428c834bbe8e4f553b17716d4435
implementation_sha: fa8ca1b1988d428c834bbe8e4f553b17716d4435
tests_commit_sha: fa8ca1b1988d428c834bbe8e4f553b17716d4435
final_head_sha: fa8ca1b1988d428c834bbe8e4f553b17716d4435
remote_head_sha: fa8ca1b1988d428c834bbe8e4f553b17716d4435
git_status_clean: false
validator_commit_sha: fa8ca1b1988d428c834bbe8e4f553b17716d4435
test_count: 80 final affected focused tests (working tree; not the full suite)
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-04B-THREE-DEADLINES__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-04b-clone
