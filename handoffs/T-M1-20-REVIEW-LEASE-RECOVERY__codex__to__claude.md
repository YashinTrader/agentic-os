# Handoff: T-M1-20-REVIEW-LEASE-RECOVERY

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Added shared automatic recovery fencing for claims and review leases. Recovery requires a tokened, start-time-validated dead consumer and every recorded review child to be provably dead, or no recorded child. Review run state is also checked. Unknown/live identities and unreadable run evidence stay fenced.
- Consumer ticks recover abandoned leases; lease acquisition also recovers under the same mutation guard before counting capacity. Durable lease_recovered audits precede removal and contain the reason and full prior owner. Tick recovery emits the matching lifecycle event. Request/run identity stays intact; existing fingerprint claims and resolved-event deduplication still gate launches.
- Added stale_review_leases, stale_review_lease_alert_active, alert_active integration, and blocked_stale_lease lifecycle reporting. Legacy and unreadable leases continue to count. The operator list/release interface remains available; list now includes unreadable records with their error rather than hiding all records behind a parse failure.
- Capacity refusal uses capacity:review with ten-second bounded backoff and zero failed attempts, bypassing startup-failure retries and failure fingerprints. A freed slot (zero active leases at the default concurrency of one) becomes eligible on the next tick. Deferral records and deferred event logs retain the human-readable reason for capacity, authentication and failures.
- Added offline deployment-layout regressions, recovery documentation, and this exact handoff path to POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review and commit-bound verification in a Git-writable session before deployment. No external action was performed.

## Decisions Made

Age never authorizes recovery. The existing consumer-owned KILL_ON_JOB_CLOSE job justifies no-recorded-child recovery; a recorded PID without creation identity remains unknown. Request records and review run IDs are preserved. Claim recovery/reacquisition and lease recovery/acquisition are serialized by the same OS mutation guard, preserving event ownership and capacity fencing. A lease held for the same assignment is a capacity refusal even when other concurrency slots remain.

## Open Questions

None blocking review.

## How to Verify My Work

Final verification: 115 discovered, 113 passed, two explicitly skipped, zero failures/errors. All required modules passed. The final 78-test run covers the changed modules and all 12 new regressions; the other required modules contribute 37 tests (including two skips). Raw evidence and aggregation: runtime/dispatch/m1-20/coverage-final-output.txt, test_layer_supervisor.txt, test_import_guard.txt, test_console_encoding.txt, test_dispatch_executor.txt, test_config_root.txt, and final-summary.json. The initial capture_required run predates six added edge-case tests; use the final 78-test run for those modules. Offline runner and raw per-module outputs: runtime/dispatch/m1-20/. The runner relocates temporary fixtures (including a pre-existing C:/tmp override) into this clone with inherited Windows ACLs; production behavior and test assertions are unchanged. Required modules run in separate processes to avoid config-root environment leakage.

```powershell
python runtime/dispatch/m1-20/capture_required.py
python runtime/dispatch/m1-20/run_offline.py tests.test_review_lease_recovery tests.test_consumer_claims tests.test_claude_event_consumer tests.test_claude_reviewer_adapter
python runtime/dispatch/m1-20/coverage_offline.py
python scripts/validate.py
git diff --check
```

Offline stdlib trace statement coverage: consumer_claims.py 85.8% (211/246), claude_event_consumer.py 90.9% (308/339), review_dispatcher.py 72.3% (305/422); combined 81.8% (824/1007). Review dispatcher uncovered lines are predominantly existing verdict/launch paths; the new recovery-before-capacity and refusal paths are exercised. Details: runtime/dispatch/m1-20/coverage.json. Coverage tooling required no dependency installation.

validate.py exit 0; git diff --check exit 0. Validator emits existing deprecated event-log warnings.

The two skipped supervisor tests are test_shutdown_terminates_owned_tree and test_real_dummy_crash_restarts_with_bounded_stderr_and_recovery; both terminate real processes, forbidden by this task. Mocked lifecycle/fencing tests run normally. New regressions first reproduced three failures and one error before production changes.

## Risks / Caveats

- Git metadata is explicitly read-only in the sandbox. No staging/commit was attempted, including the skill's TDD checkpoints. All SHA fields below identify the unchanged base, not a committed implementation. Tests cover the working tree. remote_head_sha is the existing local origin/HEAD tracking ref, without a remote query. Receiver must commit and regenerate commit-bound evidence before deployment.
- Legacy and unknown identities intentionally require operator investigation. Recovery never signals or terminates a process. Unreadable records remain capacity blockers and are surfaced for inspection.
- No session_pickup, canonical-checkout command, network, push, merge, real process termination, credential change, dependency installation or dependency audit was performed. Network prohibition prevents a dependency audit; dependencies are unchanged. Task-provided TASK_INSTRUCTIONS.md, codex_stdout.jsonl and codex_stderr.log are preserved. The existing runtime/unittest_last_run.txt is not overwritten by focused evidence.

## Recommended Next Action for Receiver

Review recovery fences and reproduction evidence, commit in a Git-writable session, and run the deployment integration gate.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-20-reviewleases
branch: agent/codex/T-M1-20-REVIEW-LEASE-RECOVERY
base_sha: 23c9cec5f570359e03b21420da607098e2e0df17
implementation_sha: 23c9cec5f570359e03b21420da607098e2e0df17
tests_commit_sha: 23c9cec5f570359e03b21420da607098e2e0df17
final_head_sha: 23c9cec5f570359e03b21420da607098e2e0df17
remote_head_sha: 23c9cec5f570359e03b21420da607098e2e0df17
git_status_clean: false
validator_commit_sha: 23c9cec5f570359e03b21420da607098e2e0df17
test_count: 115
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-20-REVIEW-LEASE-RECOVERY__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-20-reviewleases
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies unchanged; existing local Python environment used
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-20-reviewleases
