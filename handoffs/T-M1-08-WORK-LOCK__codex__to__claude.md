# Handoff: T-M1-08-WORK-LOCK
**From:** codex
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Added dispatch/work_lock.py with one durable holder per logical task across assignment reservations, local builders, supervisor launches, and manual dispatch. Exclusive record creation and OS transaction locks serialize concurrent acquisition, release, heartbeat, and supersede across threads/processes. A crashed transaction does not leave a permanently held mutex; durable work ownership remains.
- Added logical_task_id to assignments, claims, wakes, outbox results, and builder/supervisor run artifacts. Assignment parent links and YAML parent_task_id links inherit identity; explicit logical ids can split work. Direct builders also honor an active assignment's identity override. Missing parents, cyclic ancestry, ambiguous identities, and corrupt lock records fail closed.
- Enforced ownership at assignment create/claim, worker invocation, shared local-builder core before allocation, and supervisor launch, including already-claimed assignments. Codex workers claim their matching reservation and reuse the actual builder run id; a correction cannot claim its parent's reservation.
- Released and audited terminal assignment states; retained locks on build completion awaiting review, correction requests, failures, timeouts, and orphans. Reassignment and configured supervisor fallbacks explicitly supersede with actor, reason, and the complete prior record. Fallback transfers occur after the primary exits or before any process starts when its adapter is unavailable.
- Added scripts/work_lock.py acquire/release/status/supersede for manual orchestrator dispatch. Stale heartbeats are reported after 900 seconds and never grant another holder permission to acquire. Assignment readers/CLI expose live work_lock_status; the dashboard's existing assignment errors field displays stale holder/route warnings.
- Added work_lock_enabled configuration and concurrency-above-one guards in execution-policy validation, the worker, shared local-builder core, and supervisor lease acquisition. Documented identity, coordination root requirements, manual commands, recovery, and enforcement in docs/WORK_LOCK.md.
- Added 24 focused work-lock tests and updated the old duplicate-assignment expectation. Registered this handoff in POST_TEST_ALLOWLIST_EXACT before closeout.

## What Remains

- Commit the scoped working changes in a Git-writable environment. Staging failed with permission denied creating .git/index.lock; no implementation commit exists.
- Regenerate commit-bound v2 verification evidence after committing. The SHA fields below anchor the unchanged checkout for structural compatibility; they do not identify a committed implementation or attest that the existing full-suite artifact covers these changes.
- Review/deploy this coordination change separately. When dispatching into separate clones, the orchestrator must acquire against the same canonical coordinator root used by assignment/worker/supervisor routes. Independent runtime directories do not share locks. See docs/WORK_LOCK.md.

## Decisions Made

- Reserve ownership at create time, before a builder claims or launches. Resume/adoption applies only to the same assignment/holder reservation or the same run, never a second active run.
- Keep short OS transaction mutexes separate from persistent ownership. Terminating a process releases its transaction mutex but never expires its work record.
- Preserve complete prior-holder records in individual atomic audit files. Explicit release/supersede requires actor and reason. Supervisor fallback is an explicit audited supersede under its configured fallback policy.
- Use structured parent references rather than guessing relationships from task-name suffixes. Existing assignment logical ids remain authoritative for ordinary direct builder dispatch when YAML did not explicitly set an id.
- Reuse the dashboard's existing assignment warning surface to stay within the task's dispatch/orchestrator/scripts/tests/docs/config/handoff boundaries.

## Open Questions

None blocking local implementation review. The receiver owns canonical-root rollout and registration of any work already active before this lock mechanism is installed.

## How to Verify My Work

```powershell
python -m unittest -v tests.test_work_lock tests.test_assignment_channel tests.test_phase3_7c_local_builder tests.test_physical_agent_launcher tests.test_phase3_8b_assignment_loop tests.test_agent_wake_poke tests.test_layer_supervisor
python scripts/validate.py
git diff --check
```

## Verification Results

- 136 unique focused tests passed across the seven modules above. No full discovery or full test suite was run.
- Regression run: 90 tests, exit 0, 434.428 seconds, including the complete assignment, local-builder, physical-launcher, and assignment-loop modules. Evidence: runtime/dispatch/m1-08/regression-tests.txt.
- Final targeted run: 96 tests, exit 0, 65.527 seconds, covering assignment/physical-launch/wake/dashboard integration, layer supervision, and the then-current 22 work-lock tests. Evidence: runtime/dispatch/m1-08/final-targeted-tests.txt.
- Final core run after the last identity-resolution changes: 27 tests, exit 0, 62.452 seconds. This includes all 24 final work-lock tests plus LocalBuilderRunnerTests and ExecutionPolicyTests. Evidence: runtime/dispatch/m1-08/final-core-tests.txt.
- Consolidated final verification passed: 101 focused tests, Python exit 0, with PowerShell explicitly reporting focused_python_exit=0. Evidence: runtime/dispatch/m1-08/verified-final-tests.txt. This run covers all final lock tests, assignment/launcher/wake/dashboard integration, layer supervision, and the local-builder runner/policy tests.
- Earlier redirected invocations produced a PowerShell wrapper exit of 1 because unittest writes progress to stderr, despite unittest reporting OK. The consolidated run converted that output to text and explicitly propagated the Python exit code; the separate 24-test exit-confirmation run also reported Python exit 0. Earlier OK summaries are test outcomes rather than shell-wrapper success claims.
- New tests cover duplicate create/legacy claim naming the holder; correction inheritance and explicit splits; different logical tasks; a 12-thread acquisition race with exactly one winner; terminal release and failure/timeout retention; stale status/no stealing; supersede audit; real manual CLI subprocess round trip; concurrency guards; direct core rejection before allocation; worker reservation adoption; correction-parent protection; supervisor rejection, failure retention, and audited fallback; corrupt records; and heartbeat lifecycle.
- Default temporary-directory fixture setup initially failed with Windows access denied. The successful runs used runtime/dispatch/m1-08/run_focused.py, which redirects tempfile directories into this clone with inherited permissions and excludes its scratch directory from recursive fixture copies. Production permissions/code were not patched. Test evidence/scratch directories remain local under runtime.
- The initial regression exposed one obsolete test that expected duplicate assignment creation to succeed; it was updated to assert the required holder conflict and subsequently passed.
- Python compilation passed for dispatch, orchestrator, and scripts. git diff --check passed.
- python scripts/validate.py passed with only existing deprecated event warnings. The final validator run includes this handoff.
- git add failed, exit 1: unable to create .git/index.lock, permission denied. No commit, push, merge, deployment, credential change, agent CLI execution, external network call, or session_pickup occurred.

## Risks / Caveats

- This is working-tree verification. No committed-tip or remote-branch verification is claimed, and runtime/unittest_last_run.txt was not rewritten. Full-suite/commit-bound closeout must be performed separately if the receiver requires it.
- The six SHA fields below refer to the existing checkout/base, not a nonexistent implementation commit. origin/HEAD was read locally and equals this base; no remote query/push was made. git_status_clean is false because the implementation and handoff are uncommitted. Existing TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log were preserved.
- Supersede changes coordination ownership; it cannot kill an independently launched process. Operators must inspect/stop prior work before manual transfer. All routes must share a coordinator root. Manual locks without an inbox assignment are visible via CLI status.
- Existing installations need already-active manual work registered before rollout. A stale record is evidence to inspect, never authorization to steal it.
- No dependency audit was run: external network is forbidden, no dependency was changed, and Git staging was blocked.

## Recommended Next Action for Receiver

Review the scoped diff and focused evidence, commit from a Git-writable environment, and regenerate truthful commit-bound verification metadata. Configure all dispatch routes to use the same coordinator runtime before rollout. Keep the existing protected-branch and external-action gates.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-08-clone
branch: agent/codex/T-M1-08-WORK-LOCK
base_sha: 360bc5cfa634653bd2b14eb1080577311ab805c7
implementation_sha: 360bc5cfa634653bd2b14eb1080577311ab805c7
tests_commit_sha: 360bc5cfa634653bd2b14eb1080577311ab805c7
final_head_sha: 360bc5cfa634653bd2b14eb1080577311ab805c7
remote_head_sha: 360bc5cfa634653bd2b14eb1080577311ab805c7
git_status_clean: false
validator_commit_sha: 360bc5cfa634653bd2b14eb1080577311ab805c7
test_count: 136 unique focused tests (working tree; not full-suite verification)
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-08-WORK-LOCK__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-08-clone
