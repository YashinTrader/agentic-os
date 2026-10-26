# Handoff: AOS-PERF-002-IDLE-EFFICIENCY
**From:** codex
**To:** claude
**Date:** 2026-10-26
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did

Implemented change-driven idle recovery with a named 60-second fallback, file-entry fingerprints, shared run-state snapshots, read-only run lookup, and status publication on meaningful changes or a 30-second liveness interval. Recovery still runs while dispatch is paused; active run liveness remains checked each poll. The fingerprint records entry names, JSON file sizes and nanosecond mtimes, so in-place edits do not depend on Windows directory timestamp propagation. The pre-recovery fingerprint is retained so changes during a sweep trigger another pass.

Condition retries evaluate cached run states every poll, preserving their next_eligible_at deadlines and existing probe schedules. Wake queues and fail-closed dispatch controls remain checked every poll. No adaptive sleep or pickup latency change was introduced. Stuck recovery shares the sweep snapshot and already-finalized assignments are skipped by the existing durable status guard. Ownership checks and fenced terminal publication remain in their existing mutation paths.

The consumer skips full recovery/status scans only for an empty, unchanged idle queue with no outstanding claims, deferred work or leases. New pokes trigger the next poll. Deferred and owned work retain per-poll recovery, probes, age alerts and retry checks. Removed the transient idle status reset that otherwise rewrote parked status twice per poll. Idle counters accumulate in memory and publish at liveness refresh; diagnostic ages refresh then as well, while alert transitions publish immediately.

Added tests in tests/test_idle_efficiency.py and updated the consumer counter test for bounded status publication. Removed the consumer fixture's hardcoded C:/tmp directory so TEMP/TMP control its disposable state. Registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## Measurements

All runtime state was generated from local fixture templates into fresh system temporary directories: 27 runs, 15 inbox assignments, matching claims and locks, and audited-shape PAUSED control. No live runtime state was accessed or copied. The before implementation was exported from local Git object f1ef42f50f68869377d999e403ad6bc0ca0b4204 into a temporary directory with git archive. The same signed interpreter, machine, fixture generator, cProfile instrumentation and 120 warm idle ticks were used for both versions.

Final detailed numbers and the separate owned-tree sample are recorded in runtime/perf002_evidence/{before,after}/summary.json and tree-summary.json. The reproducible drivers are profile_paths.py, synthetic_fixture.py, compare_synthetic.py and profile_owned_tree.py in that directory. The tight-loop path profile excludes startup recovery and does not amortize the periodic/liveness intervals; those intervals are tested separately and exercised in the 60-second owned-tree sample.

(Builder session was cut off by model capacity before filling this section; values below are copied by the reviewer
from runtime/perf002_evidence/{before,after}/summary.json and tree-summary.json, plus the reviewer's independent run.)

| Per idle tick (synthetic: 27 runs, 15 assignments) | before f1ef42f | after |
| --- | ---: | ---: |
| builder cpu ms | 217.8 | 38.5 |
| builder direct fs calls (mkdir+stat+open+replace+listdir+scandir) | ~324 | ~53 (+99 cached DirEntry stats) |
| builder status writes | 4.0 | 0.04 |
| consumer cpu ms | 43.9 | 1.95 |
Owned-tree 60 s sample (after): 1.78 tree CPU-s/min, 2 status changes per file per minute.

Reviewer independent A/B (isolated copies of live dispatch data, dispatch paused, alternating rounds, 120 s samples):
tree CPU 7.31 -> 1.42 s/min (median), tree I/O ops 87,830 -> 17,316 /min, supervisor_status rewrites 82 -> 2 /min,
consumer status 17 -> 2 /min, RSS 99.2 -> 101.6 MB. Evidence: agentic-os-ops/perf/AOS-PERF-002/compare_idle_rounds.jsonl.

## What Remains

Review the local working-tree diff and evidence. Commit/deploy only through the owner's normal workflow; this task explicitly forbids commits. A production comparison against the Director's live sample remains outside this task's permitted access.

## Decisions Made

- Used portable entry fingerprints instead of a Windows event framework. Tests preserve directory mtime while editing a JSON file and verify discovery anyway.
- Kept active/deferred work on its existing poll cadence. Only genuinely idle expensive recovery is gated.
- Kept run_directory's write behavior backward compatible, adding create=False for load_run_state. Missing run reads no longer mkdir.
- Status timestamp/counter changes alone do not write; meaningful dispatch, failure, wake/work-lock, quota alert and lifecycle changes do.
- Did not alter enabled adapters, credentials, security classification, failure budgets, ownership fencing, pause defaults or launch authorization.

## Open Questions

None required to review this implementation. The synthetic fixture is deliberately reproducible and does not establish performance for every possible future history size.

## How to Verify My Work

Use C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe, with TEMP and TMP set to the system temporary directory outside this clone.

- Final combined command: -m unittest tests.test_idle_efficiency tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root tests.test_builder_dispatch_pause tests.test_stuck_assignment_recovery tests.test_retry_lock_continuation tests.test_layer_supervisor tests.test_launch_resilience tests.test_stop_supervisor tests.test_physical_agent_launcher tests.test_claude_event_consumer tests.test_builder_condition_retry tests.test_quota_probe
- Run scripts/validate.py and git diff --check.
- Run runtime/perf002_evidence/compare_synthetic.py for before/after profiles, and runtime/perf002_evidence/profile_owned_tree.py for a new, exclusively owned temporary supervisor tree. Both scripts require this clone as cwd and never copy live state.

(Filled by the reviewer.) Builder's final combined run did not complete before the capacity cut-off; its earlier
167-case and 38-case runs passed (TRUE exit 0). Reviewer independent run of the full combined list plus
tests.test_work_lock and tests.test_prelaunch_failure_isolation: 255 tests OK, TRUE exit 0; scripts/validate.py exit 0.

## Risks / Caveats

The first required 167-case run passed (required-tests.log/.exit, TRUE exit 0). The later focused 38-case run passed (changed-final-tests.log/.exit, TRUE exit 0). Final combined results below supersede these overlapping checks.

Three exploratory runs stalled in the pre-existing consumer fixture's hardcoded C:/tmp TemporaryDirectory call because the sandbox denied creation there; faulthandler captured the mkdtemp stack. Only those three exact commands started during this session were terminated; their TRUE native exit codes are 15, recorded in development.exit, changed-tests.exit and changed-final.exit. They did not finish their test suites. stopped-own-tests.log records the matching commands/PIDs. The fixture now uses the system temporary directory. A separate 12-case retry diagnostic passed, TRUE exit 0 (retry-diagnostic.log/.exit).

Filesystem measurement distinguishes direct filesystem API calls from DirEntry.stat metadata queries. Windows directory enumeration caches ordinary entry metadata; the latter are reported separately rather than silently omitted. This is a Python path profile, not a kernel ETW trace or an antivirus CPU measurement.

No session pickup, real assignment/claim/lock operation, live/deploy-root access, external posting, push, deployment or commit occurred. All process signaling was limited to processes started by this task or their owned descendants. No dependency installation was needed. New persistent memory is a per-supervisor run snapshot and entry fingerprint; the memory evidence reports Python allocations, while the tree sample reports process RSS.

## Recommended Next Action for Receiver

Review the diff, synthetic measurements, true exit files and test results, then decide whether to promote this change through the normal owner gate. Retain PAUSED default/fail-closed controls and do not treat synthetic testing as authorization to resume live dispatch.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/perf-002-idle-efficiency
branch: agent/codex/perf-002-idle-efficiency
base_sha: f1ef42f50f68869377d999e403ad6bc0ca0b4204
implementation_sha:
tests_commit_sha:
final_head_sha: f1ef42f50f68869377d999e403ad6bc0ca0b4204
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 216
test_exit_code:
validator_exit_code:
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/AOS-PERF-002-IDLE-EFFICIENCY__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/perf-002-idle-efficiency
dependency_install: skipped
dependency_install_reason: Existing signed runtime used; no new external dependencies.

This is an uncommitted local handoff, as required. Empty implementation/test/validator/remote SHA fields do not claim sealed committed verification or remote equality. Initial task/log/evidence inputs were already untracked. No unrelated files were modified.
