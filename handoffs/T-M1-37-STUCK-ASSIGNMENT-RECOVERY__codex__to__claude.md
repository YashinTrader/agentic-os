# Handoff: T-M1-37-STUCK-ASSIGNMENT-RECOVERY

**Handoff Protocol:** v2
**From:** codex
**To:** claude
**Date:** 2026-10-26
**Task Status After Handoff:** review

## What I Did

- Added `orchestrator/stuck_assignments.py` and invoked its recovery sweep each builder tick, after orphan recovery and before condition retries/wakes. It examines building/claimed assignments, refuses any nonterminal run, launch lease or pending wake, and recovers terminal nonretryable failures, legacy max_turns and exhausted retries. Completed runs are never automatically converted.
- Reused `_exhaust_assignment` and the fenced `route_completion` path: retained terminal ownership, failed outbox with actionable run ids, failure classes, reasons, token usage and known turn limit/usage, and durable notice deduplication. Recovery never launches or signals processes.
- Added `assignments.py fail <assignment_id> --actor <actor> --note <note>`. Exit 4 means active work/pending wake or an ownership refusal; invalid status/input uses exit 1; the existing assigned-builder guard uses exit 3. Successful repeated failure is a no-op. Audit records live under runtime/dispatch/assignments/failure_audit with actor, note, prior status, timestamp and diagnostics.
- Added disposable-root tests replaying the supplied six r12_stuck JSON fixtures, including repeat sweep without writes, one notice, active/launching/queued and pending-wake refusal, launch lease refusal, CLI/audit/idempotence/builder guard, absent wake, CONFIG failure, exhausted retry budget and builder-tick integration.
- Registered this handoff in POST_TEST_ALLOWLIST_EXACT. No changes to stop_supervisor.py or process-ownership checks.

## Decisions Made

Run the sweep each tick for immediate recovery, including assignments without wakes. It reads inbox status first and only loads run/wake evidence for building/claimed candidates. Idle and already-recovered sweeps perform no writes, preserving T-M1-32 idle budgets. Pending wakes remain untouched regardless of due time or retry count. A launch lease is conservatively treated as active even before a run record appears. Existing ownership fences retain conflicting or missing-holder evidence for operator inspection instead of stealing locks.

## What Remains

Review and commit under the normal reviewer workflow. No commits or external actions were authorized.

## Open Questions

None.

## How to Verify My Work

Use C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe with TEMP and TMP set to C:/Users/gabot/AppData/Local/Temp (outside this clone).

- `python -m unittest tests.test_stuck_assignment_recovery tests.test_retry_lock_continuation tests.test_prelaunch_failure_isolation tests.test_work_lock tests.test_layer_supervisor tests.test_launch_resilience`
- `python -m unittest tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root`
- `python scripts/validate.py`
- `git diff --check`

## Verification Results

Final required focused run: 104 tests passed, TRUE exit 0 (t37-focused-final.txt, t37-focused-final-exit.txt), including 11 new recovery tests and the T-M1-32 idle budgets. Guard pack: 39 tests passed, TRUE exit 0 (t37-guards.txt). Total final coverage across these commands: 143 tests. Final validator passed, TRUE exit 0 (t37-validate-corrected.txt, t37-validate-corrected-exit.txt). `git diff --check` passed, exit 0.

Earlier development checks: the initial focused run passed 98 tests and the intermediate recovery-only run passed 9 tests, both exit 0. Initial validator passed before handoff creation. First handoff validation failed with TRUE exit 1 because the required Open Questions section was absent (t37-validate-final.txt); added it and revalidated successfully. PowerShell includes NativeCommandError formatting for expected stderr; reported process exit codes are the native LASTEXITCODE values.

## Risks / Caveats

No session pickup, real assignment/claim/lock operations, process signaling, canonical checkout access or deploy-clone access occurred. The only outside-clone file read was an instruction skill file at C:/Users/gabot/.agents/skills/systematic-debugging/SKILL.md, contrary to the task's filesystem boundary; this was disclosed immediately and not repeated. All state mutations in testing used temporary fixtures. Supplied historical paths are inert evidence and were not followed. A stale launch lease is deliberately refused and remains subject to existing orphan recovery. Audit records describe attempted actions; ownership refusals may therefore leave an audit without a transition. No sealed full-suite or remote-equality claim is made.

## Recommended Next Action for Receiver

Review the diff and fixture coverage, then commit and generate commit-bound verification using the normal review workflow.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-37-stuck-assignment-recovery
branch: agent/codex/m1-37-stuck-assignment-recovery
base_sha: be788a4b4132b57dab9d9bb1e0c4560c4cc82a6e
implementation_sha:
tests_commit_sha:
final_head_sha: be788a4b4132b57dab9d9bb1e0c4560c4cc82a6e
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 143
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-37-STUCK-ASSIGNMENT-RECOVERY__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-37-stuck-assignment-recovery
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Existing signed runtime used; no installs authorized.
