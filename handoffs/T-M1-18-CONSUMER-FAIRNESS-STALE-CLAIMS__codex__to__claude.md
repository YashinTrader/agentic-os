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
