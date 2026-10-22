# Handoff: T-M1-27-CAPACITY-LEAK
**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did

- Persist the builder PID and OS creation identity before prelaunch work. Recover queued/launching runs only after the run PID and owning builder are proven dead. Preserve failed_launch evidence and release matching leases and work locks with run_id fences. Missing or inaccessible identity remains protected.
- Keep the wake eligible through the existing three-failure backoff/dead-letter path. Persist the logical work-lock identity before worktree allocation. Recover active runs regardless of how many newer terminal run records exist.
- Check capacity before generating a run ID or allocating a run directory/worktree. Leave the wake queued with a 10-second next_attempt_at and unchanged failure-attempt count. Deferred reports have stable content for the existing supervisor state logger. Roll back condition-retry dispatch accounting on capacity refusal.
- Add owned_run: owned_popen/Windows Job Object, file-backed captured output, cooperative heartbeat waits, and owned-tree cleanup on timeout and successful root exit. Use it for version/auth probes and worktree Git helpers. Cache successful version results by resolved executable path and mtime. Keep quota-probe heartbeats active during its bounded wait.
- Preserve unknown Windows PID identity as unknown rather than declaring an inaccessible live process dead.
- Add offline recovery/capacity/fencing/condition-retry tests and a real Windows .cmd shim with a 300-second grandchild holding stdout, plus an independently owned decoy. Update existing mocks to target the owned helper. Add this exact handoff path to POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review, commit in a Git-writable session, and regenerate commit-bound verification. This session cannot write Git metadata.

## Decisions Made

Unknown ownership is treated as live. Historical queued records without builder PID/start-time evidence cannot be automatically reclaimed safely; no inference from a restarted layer's current PID is used. Output files avoid pipe-draining hangs even when descendants inherit stdout. Heartbeats are cooperative waits, with no unconditional background heartbeat thread.

## Open Questions

None for implementation. Existing leaked records lacking owner identity require an explicitly fenced operator recovery after ownership is established.

## How to Verify My Work

Final requested/helper suites: 159 tests passed (exit 0), recorded in runtime/dispatch/m1-27/verified-suites.txt. After the final helper API and fixture adjustments, the recovery/Windows-shim/allocator recheck passed 18 tests (exit 0), recorded in allocator-recheck.txt. This covers 168 distinct tests, including nine repeated recovery/probe tests. validate.py passed (exit 0, existing deprecated v1 event warnings), recorded in validate-final.txt. git diff --check passed. Earlier captures are development evidence, not final verification; two earlier mock-timeout runs were cancelled through their own tool sessions after the fixture was changed to use a fake clock. Runtime evidence is local and Git-ignored under runtime/dispatch/m1-27/. The runner places fixtures inside this clone and changes Windows 0700 temporary-directory creation to inherited permissions to accommodate the sandbox; production assertions are unchanged. No tests are excluded.

```powershell
python runtime/dispatch/m1-27/run_offline.py tests.test_capacity_leak tests.test_prelaunch_failure_isolation tests.test_windows_write_contention tests.test_physical_agent_launcher tests.test_grok_streaming tests.test_builder_condition_retry tests.test_process_ownership_fencing tests.test_stop_supervisor tests.test_layer_supervisor tests.test_work_lock tests.test_import_guard tests.test_quota_probe tests.test_claude_event_consumer.DefaultConditionProbeTests
python runtime/dispatch/m1-27/run_offline.py tests.test_capacity_leak tests.test_phase3_4_worktree_allocator
python scripts/validate.py
git diff --check
```

## Risks / Caveats

- SHA fields identify the unchanged base HEAD, not a committed implementation. remote_head_sha is a protocol placeholder equal to local HEAD; no remote was queried. The working-tree changes were tested locally. Receiver must commit and regenerate evidence.
- Tests terminate only their own owned children, grandchildren, and decoy. No session_pickup, canonical/deploy checkout command, network, provider CLI invocation, push, merge, credentials change, or dependency installation.
- Dependency audit skipped: network forbidden and dependencies unchanged.
- Task-provided TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log are preserved.

## Recommended Next Action for Receiver

Review recovery fences and the Windows shim regression, commit, and regenerate commit-bound verification. Review any pre-existing ownerless leak separately using established process ownership evidence.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-27-capacityleak
branch: agent/codex/T-M1-27-CAPACITY-LEAK
base_sha: 543f455a1648098979af382bef5ea0ac269e4134
implementation_sha: 543f455a1648098979af382bef5ea0ac269e4134
tests_commit_sha: 543f455a1648098979af382bef5ea0ac269e4134
final_head_sha: 543f455a1648098979af382bef5ea0ac269e4134
remote_head_sha: 543f455a1648098979af382bef5ea0ac269e4134
git_status_clean: false
validator_commit_sha: 543f455a1648098979af382bef5ea0ac269e4134
test_count: 168
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-27-CAPACITY-LEAK__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-27-capacityleak

known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies unchanged
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-27-capacityleak
