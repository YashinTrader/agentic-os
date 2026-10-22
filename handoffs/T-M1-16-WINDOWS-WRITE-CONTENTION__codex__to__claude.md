# Handoff: T-M1-16-WINDOWS-WRITE-CONTENTION

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Added a 2.5-second bounded replace retry with 25ms initial backoff capped at 200ms. Retries PermissionError winerror 5/32 and OSError winerror 32/33; other errors propagate immediately. Successful writes do not consult the retry clock. JSON and context-bundle text writers share this implementation, stage complete UTF-8 content in exclusive pid-plus-random temporary files, fsync/close before replace, and clean up staging files.
- Contained heartbeat OSError failures after the atomic retry budget; loop ticks continue. Warnings are bounded to 300 characters and one per minute. Monitor persistence similarly defers filesystem failures to the next poll, retains in-memory state/process ownership, and returns captured output for normal supervisor classification. Ownership-fencing errors still propagate.
- Recovery checks PID plus recorded process start identity before salvaging output with unknown exit code. Structured provider failures and explicit plain CLI error prefixes remain distinct from tool output/narration. A shared classification helper applies the normal failure fingerprint, blocked_on, blocked_since, attempts, retry_after, retry cap, and next_eligible_at schedule. Salvaged quota/auth failures keep their lock for the existing fenced condition retry; assignment routing matches the normal blocked path. Max-turn recovery preserves the bounded continuation behavior.
- Unclassifiable dead runs become orphaned. Recovery records their evidence without refreshing a replacement's lock, then releases only a matching run-id holder with audit reason orphan_recovered. Concurrency lease cleanup also checks the run id. A different holder is never released.
- Extended ghost alerts to pre-existing orphaned/failed_launch/blocked_external supervisor records and terminal result.json-only records. Live/unknown process evidence prevents reporting. Ghost checks mark stale_reason and expose work_lock_alerts without releasing or transferring ownership.
- Checked heartbeat, supervisor-run, monitor stream, and dashboard readers: these use read_text or context-managed short-lived file handles. The layer supervisor's long-lived stderr reader consumes a process pipe, not a JSON destination. No reader change was needed.
- Updated docs/WORK_LOCK.md and added this exact handoff path to POST_TEST_ALLOWLIST_EXACT. Added 17 offline regressions in tests/test_windows_write_contention.py.

## What Remains

Receiver review, commit from a Git-writable session, commit-bound verification,
and deployment/live drill. Local implementation and focused checks are complete.

## Decisions Made

Preserved blocked-run lock retention and fenced condition retries. Newly
unclassifiable dead runs release only their own lock; pre-existing terminal
ghosts require explicit operator action. Unknown exit status never establishes
success during recovery, and unknown process liveness never establishes death.

## Open Questions

None blocking local review.

## How to Verify My Work

```powershell
python runtime/dispatch/m1-16/run_focused.py test_windows_write_contention test_prelaunch_failure_isolation test_work_lock test_builder_condition_retry test_physical_agent_launcher test_process_ownership_fencing test_quota_probe test_failure_classify test_run_deadlines test_layer_supervisor test_phase3_5_codex_context
python scripts/validate.py
git diff --check
```

- Final focused run: 166 discovered, 163 passed, 3 skipped, zero failures/errors, exit 0. Includes all requested existing modules, layer-supervisor/heartbeat coverage, context-bundle coverage, and all 17 new regressions. Evidence: runtime/dispatch/m1-16/final-focused-tests.txt and summary.json.
- The three skipped tests terminate real subprocesses, prohibited by TASK_INSTRUCTIONS.md: ProcessOwnershipTests.test_real_grandchild_terminated, LayerSupervisorTests.test_shutdown_terminates_owned_tree, and LayerSupervisorTests.test_real_dummy_crash_restarts_with_bounded_stderr_and_recovery. Mocked process lifecycle tests ran normally.
- Reproduced running record plus dead child plus captured 402 output; recovery produces blocked_quota with eligibility, the due tick launches once on the preserved worktree, the relaunch owns the lock, and exactly one successful run exists. Also verified unknown/live identity preservation, auth retry-after scheduling, audited orphan release, byte-for-byte preservation of a replacement lock, terminal/result-only ghost alerts, concurrent unique staging, retry exhaustion with unchanged destination, heartbeat survival, and real monitor-to-supervisor classification after a mid-run persistence failure.
- Validator exit 0; existing legacy event-log warnings only. Evidence: runtime/dispatch/m1-16/validate.txt. git diff --check exit 0.
- The local runner confines temporary fixtures to this clone. In its own process only, mode-0700 temporary directories use inherited Windows permissions because this sandbox cannot traverse Python 3.11's private temporary ACLs. Production permission handling is unchanged. No full suite was run; runtime/unittest_last_run.txt was preserved.

## Risks / Caveats

- The environment explicitly grants read-only access to .git. No staging or commit attempt was made. The implementation and new tests are working-tree changes; receiver must commit from a Git-writable session and regenerate commit-bound verification before rollout.
- The SHA fields below all identify the unchanged base checkout, which is also the locally stored origin/HEAD. They do not identify an implementation commit or prove publication of these changes. Focused evidence is working-tree evidence; the existing full-suite artifact belongs to an older integration run.
- The mandatory repository closeout gate exited 1: it cross-checks runtime/unittest_last_run.txt, the preserved 818-test artifact from integration commit 1f8ba22794dab8631a0c9310416e3a1a2bbde259, against this focused run. Commit, test count, output hash, and evidence metadata therefore do not match. No full-suite artifact was replaced or fabricated. See runtime/dispatch/m1-16/closeout-gate.txt; the validator invoked by that gate passed. Commit-bound verification remains receiver work.
- Initial general session instructions required session_pickup before reading files. That command was attempted against C:/Users/gabot/agentic-os before the isolated task's explicit exception was known; it failed with PermissionError creating the claim file, so no assignment was claimed. No further session pickup or canonical-repository write was attempted. All implementation, fixtures, and evidence were created inside this clone.
- No network, push, merge, process termination, remote agent dispatch, dependency change, or credential change was performed. Existing untracked TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log were preserved. No network dependency audit was run because the task forbids network and dependencies were unchanged.
- Sustained filesystem failure still propagates from atomic writers after the bounded budget. Heartbeat/monitor loops contain their own write failures as required; arbitrary supervisor status or final-outcome filesystem failures remain recoverable on the next startup.

## Recommended Next Action for Receiver

Review and commit the local diff, regenerate commit-bound v2 verification, and repeat isolated live drill C after deployment. Pre-existing ghost holders still require explicit operator release or supersede.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-16-writecontention
branch: agent/codex/T-M1-16-WINDOWS-WRITE-CONTENTION
base_sha: 4e60666cf9713ace6b4725eeccd04a15d0fc3365
implementation_sha: 4e60666cf9713ace6b4725eeccd04a15d0fc3365
tests_commit_sha: 4e60666cf9713ace6b4725eeccd04a15d0fc3365
final_head_sha: 4e60666cf9713ace6b4725eeccd04a15d0fc3365
remote_head_sha: 4e60666cf9713ace6b4725eeccd04a15d0fc3365
git_status_clean: false
validator_commit_sha: 4e60666cf9713ace6b4725eeccd04a15d0fc3365
test_count: 166
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-16-WINDOWS-WRITE-CONTENTION__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-16-writecontention
known_exempt_failures: []
raw_output_sha256: 98f094ff47d0586ed112b7f0dd241c6814f0919dcd06d079f6d75d266eb58941
repo_identity: {"origin": "https://github.com/YashinTrader/agentic-os.git", "roots": ["18ccb6e2e421044e6e21411c83513d80e38fb4ba"]}
dependency_install: skipped
dependency_install_reason: Task forbids network; dependencies unchanged; installed local environment used
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-16-writecontention
hostname: AIAG
python_version: 3.11.15
command_line: ["C:\\Users\\gabot\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe", "runtime/dispatch/m1-16/run_focused.py", "test_windows_write_contention", "test_prelaunch_failure_isolation", "test_work_lock", "test_builder_condition_retry", "test_physical_agent_launcher", "test_process_ownership_fencing", "test_quota_probe", "test_failure_classify", "test_run_deadlines", "test_layer_supervisor", "test_phase3_5_codex_context"]
timestamp: 2026-10-22T03:08:58.584978+00:00
python: C:\Users\gabot\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
