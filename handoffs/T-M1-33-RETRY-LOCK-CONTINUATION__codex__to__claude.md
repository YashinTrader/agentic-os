# Handoff: T-M1-33-RETRY-LOCK-CONTINUATION
**From:** codex
**To:** claude
**Date:** 2026-10-25
**Task Status After Handoff:** review (uncommitted working-tree delivery)
**Handoff Protocol:** v2

## What I Did
- `dispatch/work_lock.py`: reserve retry-eligible terminal ownership under `_guard`, preserve `prior_run_ids` and `last_run_state`, and fence continuation acquisition to the same assignment/holder. Upgrade legacy terminal locks only when durable terminal, retry-eligible run evidence matches their owner. A prior run cannot save over a new owner.
- `orchestrator/runtime_store.py`: reserve retry-eligible terminal runs during save; add `failure_class` and `blocked_executable` to supervisor and result JSON.
- `orchestrator/supervisor.py`: preserve continuation lineage despite intervening refused prelaunch runs; turn dead-letter/retry-budget exhaustion into actionable reviewable failures, recording run IDs and preserving ownership. Keep quota/auth condition schedules independent of duplicate wake suppression. Classify dispatch CLI launch failures with the existing shared classifier and emit deduplicated executable-identity alerts. Policy/config failures consume their wake without another automatic launch or fallback.
- `orchestrator/event_router.py`: reuse failure outbox/status/poke routing, with durable per-assignment/run completion-notice markers so replay does not create another notice.
- `tests/test_retry_lock_continuation.py`: offline continuation, concurrent-owner, stale-save, exhaustion, denial, missing-executable-plan and copied-evidence regressions. Update the existing prelaunch exhaustion assertion to require retained reviewable-failure ownership.
- `scripts/repository_verification.py`: register this exact handoff in `POST_TEST_ALLOWLIST_EXACT`.

## What Remains
Receiver review and integration. No commit, push, assignment operation against live state, deployment, network request, or install was authorized or performed.

## Decisions Made
- Existing policy is explicit in `tests.test_work_lock.SupervisorWorkLockTests.test_supervisor_failed_run_retains_owner_and_state`: reviewable failures retain their owner and terminal run state. Reuse that policy for exhaustion and blocked launches. Successful completion retains `completed` pending review. Retry-eligible terminal runs become `reserved`; audited child ownership still requires explicit supersede.
- Retain the most recent run ID on a reserved lock for existing completion fencing; append physical run IDs exactly once to lock history.
- Reuse `runtime/dispatch/alerts` and the existing failed/blocked outbox plus orchestrator-only poke path. No failed or unfinished work is marked as a successful implementation.
- Leave T-M1-30 worktree naming and T-M1-34 builder isolation/contracts/prompts/flags/AGENTS/CLI guards untouched. In particular, `agent_launcher.py` is unchanged; the supervisor wraps injected Popen to retain the exception before the launcher converts it to text.

## Open Questions
None for this implementation.

## How to Verify My Work
All Python used `C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe`. Evidence logs and the local test harness are under `runtime/dispatch/m1-33/` (ignored). The harness keeps temporary writes inside this clone and excludes its own temp directory from repository-copying fixtures.

| Verification | Tests | True exit code | Log under runtime/dispatch/m1-33/ |
| --- | ---: | ---: | --- |
| New regression module alone, final configured-path and consumed-notice assertions | 11 | 0 | new-final-tests.txt |
| Core: new regressions, work_lock, prelaunch_failure_isolation, physical_agent_launcher, process_ownership_fencing | 79 | 0 | core-verified-tests.txt |
| Core plus quota/backoff and Windows contention regressions (before final diagnostic-only refinements) | 96 | 0 | core-final-tests.txt |
| Guard pack: import_guard, dispatch_executor, console_encoding, process_ownership_fencing, provenance_deploy_root; plus launch_resilience | 59 | 0 | guard-verified-tests.txt |
| All 18 static direct importers selected against changed/new Python paths | 287 | 1 | selected-final-tests.txt |
| scripts/validate.py, including this v2 handoff | n/a | 0 | validate.txt |
| git diff --check | n/a | 0 | clean; CRLF normalization warnings only |

The 287-test run passed 286 tests and failed only `test_no_name_based_kills`, which was scanning the generated copied fixture repositories left in the inside-clone temp directory. The harness correction excludes that generated directory from root source scans; the failing check was rerun successfully in BOTH the final 79-test core and 59-test guard groups. There are no remaining exempted test failures. The final harness changes affect fixture copying and root-wide source enumeration only; production source directories remain covered. It does not bypass assertions or replace product functions.

The selected importer modules were: tests.test_achievable_evidence_seal, tests.test_builder_condition_retry, tests.test_capacity_leak, tests.test_config_root, tests.test_grok_streaming, tests.test_layer_supervisor, tests.test_mcp_isolation, tests.test_phase3_3_review_fixes, tests.test_phase3_4_1_integrity_closeout, tests.test_physical_agent_launcher, tests.test_prelaunch_failure_isolation, tests.test_process_ownership_fencing, tests.test_provenance_deploy_root, tests.test_quota_probe, tests.test_retry_lock_continuation, tests.test_run_deadlines, tests.test_windows_write_contention, and tests.test_work_lock. Selection used `scripts.impacted_tests.impacted_tests(Path.cwd(), changed_paths)` against the actual working-tree paths, including the new test; it did not rely on a committed diff.

Run any group with the signed interpreter followed by `runtime/dispatch/m1-33/run_selected_tests.py` and the full `tests.test_*` module names above. The additional imported modules stop_supervisor and postdeploy_hygiene also passed in the earlier 130-test importer run; its two quota-scheduling failures were subsequently corrected and passed in the 96- and 287-test runs. PowerShell represents captured unittest stderr as NativeCommandError text even for exit 0; the table records Python's actual LASTEXITCODE, not that formatting.

## Risks / Caveats
- This is uncommitted working-tree evidence. Blank commit-bound verification fields deliberately avoid claiming that the unchanged base contains this implementation.
- Tests use fake processes and isolated fixture assignments/locks. No live assignment, claim, lock, canonical checkout, or deployment was operated on.
- Initial verification exposed fixture assertions for the old exhaustion behavior and duplicate-wake interference with quota backoff; those were corrected. The initial 66-test run returned 1 (four failures); a subsequent 130-test importer run returned 1 (two quota scheduling failures). Later results are recorded separately rather than replacing those logs.
- The first guard run was interrupted (exit 1) after an inside-clone temporary directory caused a repository-copy fixture to recurse into its own output. Recursive cleanup was rejected by automatic approval review as blocked by policy; generated ignored temporary files were left in place. The first harness guard rerun returned 1 for its source scan of those generated copies. The final harness excludes that directory from both copying and root source scans; the final guard run returned 0.
- Completion notice deduplication covers successful routing replays. The existing poke/outbox/marker files are separate writes; this does not claim a transactional message broker across arbitrary process death between writes.

## Recommended Next Action for Receiver
Review the scoped diff and offline logs, commit the approved changes, and regenerate commit-bound verification before integration. Handle any live recovery or deployment separately under the normal owner gate.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-33-retry-lock-continuation
branch: agent/codex/m1-33-retry-lock-continuation
base_sha: 920528b5fdfa3e03965e95375481444b7457136e
implementation_sha:
tests_commit_sha:
final_head_sha: 920528b5fdfa3e03965e95375481444b7457136e
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 79
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-33-RETRY-LOCK-CONTINUATION__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-33-retry-lock-continuation
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network and installs forbidden; vendored dependencies used
