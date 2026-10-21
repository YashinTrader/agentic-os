# Handoff: T-M1-11-PROCESS-OWNERSHIP-FENCING
**From:** codex
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Added dependency-free process ownership in orchestrator/process_ownership.py. Windows children launch suspended, join a uniquely named Job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, then resume. Assignment failure cannot leave an executing uncontained child. Injected launch functions that return real Popen children also use containment. Non-Windows children start a new session and termination targets the owned process group.
- Routed agent, local builder, reviewer, and layer launches/termination through shared ownership. Normal exit also closes the Windows tree so surviving helpers cannot continue writing after completion.
- Recorded process creation time and Job/group identity in builder, supervisor, reviewer, and layer state. Recovery checks creation identity; bare historical PIDs remain unknown. Mismatched creation time is classified gone and cannot trigger a signal.
- Fenced route_completion, complete_assignment, and write_outbox_result under the same OS transaction guard used by work-lock supersede/release. The guard covers outbox, inbox/task status changes, and pokes. Nested completion calls share the transaction.
- A completing run must match both assignment and holder run, or the newest ownership audit must show release by that same run. Legacy manual completion without run_id is allowed only for a matching reserved assignment with no running run. Running holders cannot be bypassed by omitting run_id.
- Rejected results go to runtime/dispatch/fenced with submitted evidence. Superseded results leave the current lock, existing outbox, inbox, and worktree/branch untouched. Rejected runtime-state heartbeats also preserve fenced evidence and raise so the process monitor terminates its owned child.
- Added nine focused ownership/fencing tests and updated layer shutdown assertions for Job/tree termination. Registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## What Remains

Review and commit from a Git-writable environment. Staging failed with permission denied creating .git/index.lock, so no implementation commit exists. No push is authorized by this task.

## Decisions Made

- Process selection never uses executable names. Windows termination uses the retained Job handle; POSIX group signaling requires matching root creation identity.
- Keep work ownership on completion awaiting review. Fence rejection does not release any work lock or delete a branch/worktree.
- Hold the short lock transaction through completion side effects to prevent check/write races with replacement ownership.
- Use only the requested focused modules. Do not regenerate runtime/unittest_last_run.txt or claim full-suite or committed-tip verification.

## Open Questions

None blocking local review. Non-Windows group behavior needs execution on a non-Windows host; this environment verified the real Windows Job path.

## How to Verify My Work

```powershell
python runtime/dispatch/m1-11/run_focused.py
python scripts/validate.py
git diff --check
```

The local focused runner selects only test_work_lock, test_run_deadlines, test_layer_supervisor, test_builder_condition_retry, test_claude_event_consumer, test_physical_agent_launcher, test_mcp_isolation, test_assignment_channel, and test_process_ownership_fencing. It substitutes inherited-permission scratch directories inside this clone for tempfile fixtures because default Windows temporary-directory ACLs deny access in this environment. It does not patch production ownership/locking logic.

## Verification Results

- The final focused run covers 159 tests (150 existing and nine new); see runtime/dispatch/m1-11/verified-final-tests.txt for its authoritative result.
- Earlier final regression: 156 tests passed in 58.922 seconds, Python exit 0; runtime/dispatch/m1-11/final-focused-tests.txt. Three additional completion/audit/race checks passed in the nine-test new module; runtime/dispatch/m1-11/final-new-tests.txt.
- Real Windows test launches Python -> Python grandchild, proves the grandchild alive, terminates the owning Job, and proves the grandchild gone. It also exercises a wrapped Popen factory. No unrelated process is targeted.
- New tests cover PID creation mismatch/no signal, product-code static ban on name-based kills, late completed/failed/blocked outcomes, direct complete/outbox entry points, omitted-run bypass, unchanged existing outbox/inbox/lock, preserved worktree evidence, normal holder completion and poke, same-run release, superseded release rejection, stale runtime audit, and an attempted concurrent supersede during outbox writing.
- validate.py passed before handoff, exit 0, with existing deprecated-event warnings; final validation includes this handoff. git diff --check passed.
- Initial default-temp attempts hit access-denied fixture errors; the first regression invocation stalled before reporting tests. That invocation was stopped only after matching its exact test arguments, creation time, clone cwd, and absence of children. Its replacement focused runs use clone-local scratch directories. An earlier 156-test pass exposed one normal-exit test-double cleanup issue, fixed before the passing run above.
- Git staging failed: unable to create .git/index.lock, permission denied. No commit, push, merge, network, credential change, session pickup, or full suite occurred. No dependency was added; network-backed dependency auditing was not run.

## Risks / Caveats

- This is working-tree evidence. The SHA fields below identify the existing checkout/base only; they do not claim this implementation or its focused tests were committed. origin/HEAD was resolved locally, without contacting a remote. Full-suite and commit-bound repository closeout remain unverified by explicit task instruction.
- Windows Job support fails launch closed if containment or resume cannot be established. Historical run records without creation time are not treated as positively live and are not signaled.
- Non-Windows creation identity uses Linux /proc start ticks, or ps creation/state output on other POSIX systems. That path is implemented but not executed on this Windows host. If the POSIX group leader is already gone, termination conservatively refuses to signal a group without a matching leader identity.
- Original TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log are preserved as existing untracked files. Local test evidence/runner/scratch are under ignored runtime/dispatch/m1-11.

## Recommended Next Action for Receiver

Review the process ownership and fencing diff, commit in a Git-writable environment, and perform any required non-Windows and commit-bound verification separately. Preserve this task's no-push boundary.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-11-ownership
branch: agent/codex/T-M1-11-PROCESS-OWNERSHIP-FENCING
base_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
implementation_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
tests_commit_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
final_head_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
remote_head_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
git_status_clean: false
validator_commit_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
test_count: 159 focused working-tree tests; not full-suite/committed verification
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-11-PROCESS-OWNERSHIP-FENCING__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-11-ownership
