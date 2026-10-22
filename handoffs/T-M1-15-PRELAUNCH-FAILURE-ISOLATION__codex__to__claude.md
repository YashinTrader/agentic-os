# Handoff: T-M1-15-PRELAUNCH-FAILURE-ISOLATION
**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Persisted supervisor run evidence before acquiring a run lock. Added pre-launch cleanup covering validation/allocation returns and exceptions, task/adapter resolution, and spawn failures. Cleanup releases only the attempt's assignment/run-fenced holder and writes an audit reason; a replacement holder remains protected.
- Added three-attempt wake retry handling with persistent 30/60-second backoff. Exhausted wakes move into runtime/dispatch/wake_queue/dead_letter/<agent>/ with reason, attempts, first/last failure times, and dead-letter time. Supervisor status exposes wake_alerts.
- Re-evaluate blocked builders every tick before inspecting queued wakes. Failed, skipped, and deferred heads permit inspection of later wakes. Tick launches have a one-process budget, including post-process fallback; missing-adapter fallback can still resolve before the first start.
- Startup recovery reports missing-run holders with no known live process as stale ghost_holder locks, exposes work_lock_alerts, and never steals them. It checks both lock and assignment-lease process evidence.
- Documented lifecycle exceptions, retry scheduling, and ghost recovery in docs/WORK_LOCK.md. Added this exact handoff path to POST_TEST_ALLOWLIST_EXACT.
- Added 15 focused regressions, including the real allocator's invalid HEAD base-SHA validation after changes_requested, bounded retries/dead-lettering, due quota recovery with queued poison, two independent valid wakes, deferred heads, malformed JSON, spawn failures, adapter failures, explicit supersede fencing, live-lease exclusion from ghost reporting, and restart completion of an interrupted dead-letter move without a fourth attempt.

## What Remains

- Receiver review and commit from a Git-writable session. No implementation commit exists in this session.
- Canonical rollout and any live drill remain receiver-owned; this clone used offline fixtures and fake processes.

## Decisions Made

- Chose audited release for attempts that never start an agent. Run records are persisted before lock acquisition and failures retain evidence. Adapter-unavailable records retain blocked_no_adapter classification while releasing their pre-launch lock. Failures after a real process starts keep M1-08 ownership retention.
- Failed-launch and unavailable-adapter attempts may retry the same assignment; the wake's durable retry budget bounds these retries. Post-start provider failures continue through condition-retry scheduling.
- Ghost marking adds stale_reason without changing holder, route, run id, or ownership state. Only explicit release/supersede grants replacement ownership.
- Due blocked retries get first launch opportunity each tick; eligible queued wakes are scanned until one starts. process_once suppresses immediate post-process fallback so it cannot start a second process in a tick. Direct process_wake_signal callers retain the existing explicit fallback behavior, with separate fallback pre-launch evidence/cleanup.

## Open Questions

None blocking local review.

## How to Verify My Work

```powershell
python runtime/dispatch/m1-15/run_focused.py test_prelaunch_failure_isolation test_work_lock test_builder_condition_retry test_physical_agent_launcher test_process_ownership_fencing test_quota_probe test_failure_classify test_run_deadlines
python scripts/validate.py
git diff --check
```

- Final combined focused run: 128 tests passed, exit 0; evidence runtime/dispatch/m1-15/final-focused-tests.txt and summary.json. This includes all 15 new regressions and all 113 tests from the seven requested existing modules.
- Repository validator: exit 0. git diff --check: exit 0.
- Local runner: runtime/dispatch/m1-15/run_focused.py. Windows sandbox traversal failed for tempfile's mode-0700 private directories, including inside this clone. The runner confines temporary fixtures to this clone and uses inherited permissions for mode-0700 directory creation in its own test process. Production permissions and code are unaffected. No full-suite artifact was overwritten.

## Risks / Caveats

- This is working-tree verification. SHA fields below identify the unchanged base checkout and do not claim committed implementation or commit-bound test evidence. For offline v2 structural compatibility, remote_head_sha identifies the unpublished local candidate HEAD; it does not assert publication. The locally recorded origin/HEAD is a3cc0f41392a4bd5bcc4642fcd4bb95d7d978146; no fetch occurred.
- Session permissions explicitly grant read-only access to .git. No staging/commit attempt was made. No dependency changes or network dependency audit were needed; network is forbidden by the task.
- Existing untracked TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log were preserved.
- No session pickup, full suite, network, push, merge, remote agent dispatch, or credential change was performed.
- Real provider CLI/API behavior was not exercised. Existing ghost holders require an operator's explicit release or supersede.

## Recommended Next Action for Receiver

Review the diff and focused evidence, commit from a Git-writable session, then regenerate commit-bound v2 verification evidence before canonical rollout. Re-run the isolated drill to verify live scheduling and operator-visible alerts.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-15-prelaunch
branch: agent/codex/T-M1-15-PRELAUNCH-FAILURE-ISOLATION
base_sha: 9ab519ebe4491f635ae48dfe2b03ee48a2f347e7
implementation_sha: 9ab519ebe4491f635ae48dfe2b03ee48a2f347e7
tests_commit_sha: 9ab519ebe4491f635ae48dfe2b03ee48a2f347e7
final_head_sha: 9ab519ebe4491f635ae48dfe2b03ee48a2f347e7
remote_head_sha: 9ab519ebe4491f635ae48dfe2b03ee48a2f347e7
git_status_clean: false
validator_commit_sha: 9ab519ebe4491f635ae48dfe2b03ee48a2f347e7
test_count: 128 focused tests (working tree; not the full suite)
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-15-PRELAUNCH-FAILURE-ISOLATION__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-15-prelaunch
