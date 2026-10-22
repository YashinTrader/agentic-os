# Handoff: T-M1-18-CONSUMER-FAIRNESS-STALE-CLAIMS

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Replaced head-only selection with an ordered scan. Claims and auth-ineligible deferrals are skipped; resolved duplicates are archived before deferral checks. Only one assignment is selected per tick. Pre-PID startup failures retain their bounded retry, but observing a child PID prevents another launch that tick.
- Added atomic claims with consumer PID, OS creation time, unique token and review child identity. The dispatcher records the child before blocking in the monitor; later exit cannot erase its recorded creation time. Child updates and cleanup check the consumer token.
- Added guarded dead-claim recovery requiring both consumer and child to be provably dead and no resolved fingerprint. Unknown identities and inaccessible OS information fence recovery. Recovery writes durable claim_recovered audit evidence, emits the matching state event, and reacquires under one OS guard.
- Added explicit list/release CLI for claims and review leases, with actor/reason audits and resolved/live/unknown-process refusal. Lease checks consult review run state; claim checks consult the matching lease. Lease writes and operator mutations share the guard; new leases also identify the dispatcher before child startup.
- Added stale legacy claim fingerprint/assignment/age alerts and reset inherited active-review lifecycle fields every tick. Added focused regressions, recovery documentation, deployment documentation link, and this exact handoff path to POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review, commit in a Git-writable session, and commit-bound verification before deployment. No deployment or remote action was requested or performed.

## Decisions Made

Legacy records require explicit operator investigation and release; age never authorizes recovery. Missing child identity on a new claim is unknown, including a crash during startup. Claim and matching lease release are separate explicit commands; automatic claim recovery does not override review-lease capacity. Durable audit records precede removal. Liveness uses OS creation identity and distinguishes access errors from confirmed death/PID reuse.

## Open Questions

None blocking review. Records with incomplete new process identity remain fenced and require investigation rather than automatic release.

## How to Verify My Work

Final focused verification: 192 discovered, 189 passed, 3 skipped, no failures/errors. Raw output: runtime/dispatch/m1-18/required-tests-raw.txt. The capture wrapper preserves the Python subprocess exit code and raw stdout/stderr (PowerShell's direct stderr redirection otherwise labels unittest output NativeCommandError).

```powershell
python runtime/dispatch/m1-18/capture_required.py
python runtime/dispatch/m1-18/run_coverage.py
python scripts/validate.py
git diff --check
```

The focused runner includes consumer claims, claude_event_consumer, claude_reviewer_adapter, windows_write_contention, prelaunch_failure_isolation, work_lock, layer_supervisor, process_ownership_fencing, config_root, run_deadlines and physical_agent_launcher. It redirects temporary fixtures to ignored runtime/__pycache__/ inside this clone with inherited Windows ACLs. No production tempfile behavior is changed.

The three skipped tests explicitly kill real processes: ProcessOwnershipTests.test_real_grandchild_terminated, LayerSupervisorTests.test_shutdown_terminates_owned_tree, and LayerSupervisorTests.test_real_dummy_crash_restarts_with_bounded_stderr_and_recovery. Mocked lifecycle/fencing tests run normally.

Offline stdlib trace verification: 62 tests passed; statement coverage is 80.4% for orchestrator/consumer_claims.py, 90.1% for orchestrator/claude_event_consumer.py, and 90.0% for scripts/consumer_claims.py. Details: runtime/dispatch/m1-18/coverage.json. The coverage package is absent; no dependencies were installed.

## Risks / Caveats

- The sandbox explicitly grants read-only access to .git. No stage/commit attempt was made, including TDD checkpoint commits. All SHA fields below identify the unchanged base checkout, not the implementation diff. remote_head_sha is the existing local origin/HEAD tracking ref; the remote was not queried. These are working-tree tests, not commit-bound deployment evidence.
- An additional, non-required provenance suite exposes a pre-existing assertion in test_provenance_deploy_root.StateRootTests.test_layer_parent_uses_state_and_children_use_deployed_code: it expects command[-2:] to be --state-root, while T-M1-17 appends --config-root. Neither that test nor the parent command construction changed here. Supplemental output is preserved in runtime/dispatch/m1-18/final-focused-tests.txt; that run had one failure and three skips. The required T-M1-17 config-root tests pass. An earlier supplemental phase3_3_review_fixes run passed (84 tests with overlapping consumer/reviewer tests); it is not counted as final verification.
- A crash before the child creation identity is recorded cannot prove child death and intentionally prevents auto-release. Legacy matching leases can still block review capacity until explicitly released by an operator. No live/unknown recorded process is automatically overridden.
- Task-provided TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log are preserved. runtime/unittest_last_run.txt is untouched; the older integration artifact is not this run. Receiver must regenerate commit-bound v2 evidence after committing.
- No canonical-checkout commands, session_pickup, push, merge, network, process termination, credential changes, or dependency installation/audit occurred. The task forbids network, so no pip audit was run; dependencies are unchanged.

## Recommended Next Action for Receiver

Review and commit the diff in a Git-writable session, regenerate commit-bound verification, then inspect claims/leases using the documented state-root CLI before deploying. Explicitly investigate/release the reported legacy claim and stale lease if abandoned; confirm newer pokes proceed and current consumer lifecycle is truthful.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-18-consumerfairness
branch: agent/codex/T-M1-18-CONSUMER-FAIRNESS-STALE-CLAIMS
base_sha: 953380d3180aa0a99f924d0043bae435370ee94a
implementation_sha: 953380d3180aa0a99f924d0043bae435370ee94a
tests_commit_sha: 953380d3180aa0a99f924d0043bae435370ee94a
final_head_sha: 953380d3180aa0a99f924d0043bae435370ee94a
remote_head_sha: 953380d3180aa0a99f924d0043bae435370ee94a
git_status_clean: false
validator_commit_sha: 953380d3180aa0a99f924d0043bae435370ee94a
test_count: 192
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-18-CONSUMER-FAIRNESS-STALE-CLAIMS__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-18-consumerfairness
known_exempt_failures: []
raw_output_sha256: c9fa8948b53d07ddead182803eed868163731c4effb7d6c7e8b5f4a64abd664c
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies unchanged; existing local Python environment used
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-18-consumerfairness


## T-M1-18B

Review follow-up F1/F2 implemented in this isolated clone. This section supersedes
above caveats about no-child recovery and the provenance assertion.

- `acquire` recovers a tokened claim only when its consumer is provably dead and
  either no child PID was recorded or the recorded child is provably dead. Audit
  reasons distinguish these cases. The consumer-owned KILL_ON_JOB_CLOSE job
  prevents an unrecorded review child from surviving its consumer.
- `stale_claims` alerts on foreign tokened claims whose consumer is dead or
  unknown; both consumer call sites supply the current token to exclude their
  own claim. Live foreign consumers remain excluded.
- `release` skips evidence with PID None as no process recorded. Recorded PIDs
  with missing creation identity or unknown liveness still refuse release.
- The provenance test now pins the last four arguments to state root and deployed
  config root; its other assertions are unchanged. Recovery documentation updated.
- Regressions verify start-time-validated no-child recovery and exactly one review,
  unknown-owner alerts without recovery, current-token/live-owner alert exclusion,
  audited no-child release, and recorded unknown-child refusal. Existing recorded
  alive/unknown child recovery fences remain covered.

Verification: new regressions first reproduced two failures and one error; all
24 claim tests now pass. The initial direct unittest invocation hit sandbox ACL
errors in TemporaryDirectory; the existing clone-local run_focused.py runner
uses inherited ACLs and clone-local fixtures without changing production code.
The combined suite hit a config-root environment leak into the work-lock fixture;
required modules are rerun in separate processes, preserving test isolation.
Artifacts: runtime/dispatch/m1-18/followup-test_*.txt and followup-claims.txt.
Offline trace run: 66 tests passed; consumer_claims statement coverage 81.3%,
claude_event_consumer 90.1%, claims CLI 90.0% (coverage.json).
`python scripts/validate.py`: exit 0, existing deprecated-log warnings only.
`git diff --check`: exit 0.

No push, merge, network, process termination, dependency installation, or commands
against the canonical checkout. Git metadata is read-only in this sandbox, so no
TDD checkpoint or implementation commits were made. Changes remain reviewable in
the working tree on the existing branch. No dependency audit was run because
network is forbidden and dependencies are unchanged.

Final required-module results (separate processes, all exit 0): consumer_claims
24, claude_reviewer_adapter 25, provenance_deploy_root 16, config_root 7,
claude_event_consumer 17, layer_supervisor 19, windows_write_contention 17,
prelaunch_failure_isolation 15, work_lock 24: total 164 tests, 162 passed and
2 skipped. Skips are test_shutdown_terminates_owned_tree and
test_real_dummy_crash_restarts_with_bounded_stderr_and_recovery, because the
task forbids killing processes. The work-lock failure from the combined run
passes under module process isolation; no work-lock code or tests were changed.

## T-M1-18C

Fixed entrypoint test environment isolation while preserving all T-M1-18B
working-tree changes and assertions. Searched all tests/ for direct main()
calls: provenance tests, the achievable evidence seal test (including its
nested verifier invocation), and the claims CLI test now use
patch.dict(os.environ, {}, clear=False). ConfigRootTests already restores the
environment through setUp/addCleanup; clear=False is now explicit there.

Added a guard invoking the real orchestrator main with process_once mocked.
It verifies both roots are exported inside isolation, then checks the entire
environment is restored, including absent roots and pre-existing root values.

Verification uses the existing clone-local ACL-compatible run_focused.py runner:
the literal python -m unittest tests.test_provenance_deploy_root tests.test_work_lock
command encountered sandbox TemporaryDirectory permission errors. The same two
modules pass together: 41 tests, exit 0. Claims plus work_lock also pass together:
48 tests, exit 0. No assertions were weakened and no production code was changed
for T-M1-18C. The full suite was not run, as instructed.

python scripts/validate.py: exit 0 (existing deprecated-log warnings only).
No push, merge, network, process termination, or canonical-checkout commands.

Combined importer check: test_achievable_evidence_seal, test_config_root,
test_provenance_deploy_root, and test_work_lock, plus changed test_consumer_claims:
76 tests passed together in one process. This covers every test module importing
scripts.run_* (including from scripts import run_*) or dispatch.roots.
Output: runtime/dispatch/m1-18/isolation-combined.txt.
git diff --check: exit 0.
