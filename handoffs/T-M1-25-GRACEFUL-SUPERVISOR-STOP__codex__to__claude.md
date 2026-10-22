# Handoff: T-M1-25-GRACEFUL-SUPERVISOR-STOP

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working-tree delivery; commit-bound closeout pending)
**Handoff Protocol:** v2

## What I Did

- Added scripts/stop_supervisor.py with audited requester/reason/token/time, instance-targeted requests, a default 90-second wait, identity-based process verification, and exit codes 0 graceful, 3 forced-owned, 2 refused/failed.
- The running LayerSupervisor polls requests before each iteration, uses its existing planned shutdown, and publishes stopped_by_request only after cleanup finishes. Status retains the root PID/start time, named root Job, instance token and all observed layer shim/interpreter identities, including prior child restarts.
- Added a named Windows supervisor Job containing the supervisor and its descendants. Forced shutdown retains the root process handle, validates creation time, opens the recorded Job, verifies root membership, revalidates immediately before TerminateJobObject, and verifies recorded identities are gone afterward. It never selects by executable name or targets a decoy Job.
- Added audited maintenance on/off, a startup maintenance fence before configuration/layer launch, and OS instance/control/operator locks. Concurrent starts and live legacy status are fenced; stale stop tokens cannot stop replacement instances.
- Updated docs/DEPLOYMENT_ROOTS.md with the maintenance, restart and rollback procedure, interrupted-work semantics and evidence retention. Registered this handoff in POST_TEST_ALLOWLIST_EXACT.
- Added real-process tests with fake builder/reviewer layers, including forced stop with an untouched same-executable decoy, root creation revalidation, foreign Job refusal, maintenance, duplicate instance refusal, stale requests, restart and old/new/old rollback.

## What Remains

Receiver review and commit-bound closeout in a session with writable Git metadata. This sandbox grants only read access to .git, so no staging or commits were attempted. The user forbids push, merge and network. No implementation commit or remote-tip verification is claimed. Empty commit-bound fields below intentionally mean pending, rather than invented SHAs.

## Decisions Made

The instance token fences requests across restarts; an OS file lock closes the concurrent-start window that status-only checks leave open. Maintenance mutation and initial startup publication share a short control lock. Stop operators serialize separately while the supervisor continues polling and shutting down.

Windows Job membership supplies tree ownership across consoles, including venv shim/interpreter pairs and in-flight agent descendants. PID/start-time validation remains mandatory. The root Job deliberately has no kill-on-close flag; existing child Jobs keep their existing kill-on-close behavior. The supervisor's root Job handle lasts until process exit. If the recorded root is gone, reused or unreadable, surviving children are never independently signaled. POSIX fallback requires a validated root-owned process group and is not the Windows deployment acceptance environment.

In-flight builders are interrupted through the existing process-monitor cleanup, which terminates owned agent processes before unwinding. Reviews use the existing cancellation path (review_failed/cancelled), release their review lease and finish consumer-claim cleanup when cooperative unwinding completes. Forced cleanup can leave last-running state for existing orphan/claim recovery. This change does not approve assignments or erase run state, logs, prompts, worktrees or prior attempt evidence.

## Open Questions

None blocking implementation review. Legacy supervisors without root creation identity or named Job evidence deliberately need separately validated shutdown before upgrading.

## How to Verify My Work

Final measured result: 71 tests passed, zero failures or skips. validate.py exits 0; git diff --check passes.

The required suite comprises tests.test_stop_supervisor, tests.test_layer_supervisor, tests.test_process_ownership_fencing, tests.test_provenance_deploy_root, tests.test_config_root, tests.test_console_encoding and tests.test_dispatch_executor. Run the measured offline capture in this sandbox:

```powershell
python runtime/dispatch/m1-25/verify_required.py
python scripts/validate.py
git diff --check
```

The offline fixture runner uses inherited temporary-directory permissions because this Windows sandbox cannot access Python's default mode-0700 temp directories. It excludes this clone's Git metadata and runner temporary artifacts when copying the repository, while preserving Git stores created by provenance tests. Production assertions are unchanged. All test processes are created and cleaned up by their own fixtures; agents are fakes. Raw final results and measured Test Evidence are retained in runtime/dispatch/m1-25/required-final.txt and test-evidence.md. Earlier debug logs are superseded by required-final.txt.

## Risks / Caveats

- Working-tree verification is not commit-bound release verification. The entire repository suite was not run; the task's seven required modules were run. The evidence's tests_commit_sha is the unchanged checked-out base, not a commit containing these edits. Commit and rerun the repository's normal verification workflow before deployment.
- Maintenance-only on/off does not stop a running supervisor. Combine on with actor/reason for the fenced maintenance-stop procedure. Exit 2 requires investigation before cleanup, including unknown identities or a tree exit without stop acknowledgement.
- Grace remains 20 seconds per layer, sequentially. The 90-second default allows both layers to unwind. An explicitly shorter timeout can force the entire owned Job before the child grace periods expire.
- No session_pickup, canonical-checkout command, deployment-checkout command, network, push, merge, dependency installation, credential change or termination of pre-existing processes. Dependency security audit was not run because network is forbidden and dependencies are unchanged.
- TASK_INSTRUCTIONS.md and the task transcript files are preserved as supplied.

## Recommended Next Action for Receiver

Review the process-identity/Job fence and maintenance/startup serialization, commit the implementation plus allowlist and handoff event in a writable session, regenerate full-suite commit-bound v2 evidence, and perform authorized deployment separately.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-25-gracefulstop
branch: agent/codex/T-M1-25-GRACEFUL-SUPERVISOR-STOP
base_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
implementation_sha:
final_head_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
remote_head_sha:
git_status_clean: false
validator_commit_sha:
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: none
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-25-gracefulstop

### Test Evidence

tests_commit_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
test_count: 71
test_exit_code: 0
known_exempt_failures: []
raw_output_sha256: 9f04ac0e50db2344f127b11843528e9aeff5d3f910eaf362b3b4251bd5e99f33
repo_identity: {"origin": "https://github.com/YashinTrader/agentic-os.git", "roots": ["18ccb6e2e421044e6e21411c83513d80e38fb4ba"]}
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies already installed and unchanged
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-25-gracefulstop
hostname: AIAG
python_version: 3.11.15
command_line: ["C:\\Users\\gabot\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe", "C:\\Users\\gabot\\agentic-os-worktrees\\m1-25-gracefulstop\\runtime\\dispatch\\m1-25\\run_offline.py", "tests.test_stop_supervisor", "tests.test_layer_supervisor", "tests.test_process_ownership_fencing", "tests.test_provenance_deploy_root", "tests.test_config_root", "tests.test_console_encoding", "tests.test_dispatch_executor"]
timestamp: 2026-10-22T18:26:13Z
python: C:\Users\gabot\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
