# Handoff: T-M1-21-REVIEW-ATTEMPT-EVIDENCE

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Allocate a fresh review run ID whenever a launch reservation or prior run/prompt/log evidence exists. Normal first review retains its original run ID and existing artifact paths.
- Publish attempt.json before launch, retain ordered prior_review_run_ids, and record recovery audit paths and contents. Update the lease and request to the latest run before launching, preserving consumer_claims child liveness lookup.
- Finalize prior running/queued state as abandoned, retaining PID, process creation identity and start time, with recovery reason and completion time. Atomically save exact original state bytes to review_run.before_abandonment.json before finalization. Preserve context, prompt, stdout and stderr of previous attempts.
- Keep existing claim/lease recovery fences, capacity, fairness, deferral and applied-request deduplication unchanged.
- Add three regressions: crash/recovery preserving artifacts with one resolution; normal single-attempt files; repeated prelaunch reservations with complete lineage and latest-child lookup.
- Document the storage policy in docs/REVIEW_ATTEMPT_EVIDENCE.md and update docs/CONSUMER_CLAIM_RECOVERY.md. Add this handoff path to POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review, commit, and commit-bound verification in a Git-writable session. Implementation and tests are complete in this working tree.

## Decisions Made

A review run ID identifies an attempt. A request remains the assignment-level pointer to its latest attempt. Lineage is in attempt.json and the request; abandoned review_run.json remains readable by existing state readers. A pristine snapshot reconciles byte-for-byte preservation with finalizing the last known state. Terminal states remain terminal. Retries after ordinary failure need no recovery audit; recovered attempts link the matching durable claim/lease audits.

## Open Questions

None blocking review.

## How to Verify My Work

Required suites passed: 106 tests, zero failures or skips (96 core, 3 console, 7 executor). The final 15-test recovery run passed after changing snapshot writes to atomic publication. validate.py exit 0; git diff --check exit 0.

Core modules: tests.test_review_lease_recovery, tests.test_consumer_claims, tests.test_claude_reviewer_adapter, tests.test_claude_event_consumer, tests.test_prelaunch_failure_isolation. Consumer deferred/backoff/fairness regressions are included. Separate console and executor suites passed.

Evidence under runtime/dispatch/m1-21/: core-final.txt, recovery-final.txt, console-final.txt, validate-final.txt. The successful executor suite was observed directly in tool session 84273: 7 tests in 101.182s, OK, exit 0. executor-final.txt belongs to an earlier capture attempt and is not the authoritative successful executor evidence. The offline runner moves temporary fixtures into this clone and uses inherited permissions because Windows Python's 0700 temporary-directory ACL fails under this sandbox. Repository-copy fixtures exclude runner temp artifacts, Git metadata and task transcript files. Production test assertions are unchanged.

```powershell
python runtime/dispatch/m1-21/run_offline.py tests.test_review_lease_recovery tests.test_consumer_claims tests.test_claude_reviewer_adapter tests.test_claude_event_consumer tests.test_prelaunch_failure_isolation
python runtime/dispatch/m1-21/run_offline.py tests.test_console_encoding
python runtime/dispatch/m1-21/run_offline.py tests.test_dispatch_executor
python scripts/validate.py
git diff --check
```

## Risks / Caveats

- Git metadata is read-only in this sandbox. No staging or commit attempted. SHA fields identify the unchanged base; tests cover the working tree. Receiver must commit and regenerate commit-bound evidence before deployment.
- Initial attempts hit temporary-directory ACL failures; a subprocess capture using bare python selected an interpreter without PyYAML. Final captures use sys.executable and inherited fixture permissions. Some earlier repository-copy test processes were slow; none were killed, as required.
- No session_pickup, canonical-checkout command, network, push, merge, process termination, dependency installation or credential changes. Dependency audit omitted because network is forbidden and dependencies are unchanged.
- Task-provided TASK_INSTRUCTIONS.md, codex_stdout.jsonl and codex_stderr.log are preserved. Runtime evidence is ignored by Git and should be retained with the review bundle.

## Recommended Next Action for Receiver

Review the crash reproduction and lineage publication order, commit in a writable session, and regenerate verification at the committed tip before deployment.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-21-reviewevidence
branch: agent/codex/T-M1-21-REVIEW-ATTEMPT-EVIDENCE
base_sha: d17490d84b87f0b378dae72193d0cc94fe44027a
implementation_sha: d17490d84b87f0b378dae72193d0cc94fe44027a
tests_commit_sha: d17490d84b87f0b378dae72193d0cc94fe44027a
final_head_sha: d17490d84b87f0b378dae72193d0cc94fe44027a
remote_head_sha: d17490d84b87f0b378dae72193d0cc94fe44027a
git_status_clean: false
validator_commit_sha: d17490d84b87f0b378dae72193d0cc94fe44027a
test_count: 106
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-21-REVIEW-ATTEMPT-EVIDENCE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-21-reviewevidence
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies unchanged
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-21-reviewevidence

## T-M1-21B

Implemented legacy PID evidence evaluation in consumer_claims.process_liveness:
OS-confirmed absence/exit is dead even without a recorded creation identity.
Readable creation after the PID-holding record's own started_at / claimed_at /
acquired_at proves reuse; earlier/equal or unreadable creation remains unknown.
Windows uses the existing kernel/process_ownership helpers; Linux converts /proc
start ticks using boot time. No PID signaling is used. Evidence tuples retain
their originating record timestamp, including review_run.json rather than its
parent lease timestamp. Automatic recovery retains its token and creation
identity requirements; tokenless claims/leases never recover automatically.

Operator claim/lease release now snapshots and finalizes referenced running or
queued review states as abandoned immediately, with completion time, operator
reason and the exact durable audit path/content. Existing logs and artifacts
remain intact. Claim release also evaluates and finalizes matching lease run
evidence. Terminal run states stay terminal. The T-M1-21 uncommitted work is
preserved.

Regressions cover absent legacy review PID, audited claim and lease release,
immediate abandonment and byte preservation, capacity becoming available to a
fresh review, newer/equal/older/unreadable Windows creation evidence, lease
release refusal and reuse acceptance using the review's own timestamp, and
Linux boot/tick conversion. Updated the existing private evidence tuple assertion
for the added originating timestamp and made the incomplete-identity refusal
fixture explicitly represent unreadable creation rather than depend on PID 111.

Verification: 103 core/consumer/deferred/reviewer/recovery/console tests passed
(exit 0); 7 executor tests passed (OK). validate.py exit 0; git diff --check exit 0.
Evidence: runtime/dispatch/m1-21/all-core-21b.txt, executor-21b.txt,
liveness-console-21b.txt, validate-21b.txt. Earlier *21b* captures showing failures
are superseded by all-core-21b.txt. Used the existing isolated offline fixture
runner. PowerShell reports native stderr as NativeCommandError in captures;
unittest summaries and the final core runner exit confirm success.

Changes remain uncommitted for receiver review. No network, session_pickup,
canonical-checkout commands, push, merge, dependency installation or process
termination performed. No dependencies changed. This section supersedes the
prior handoff's test totals for the combined working tree: 110 unique tests.
