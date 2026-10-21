# Handoff: T-M1-06-CLI-ENCODING
**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (working tree)
**Handoff Protocol:** v2

## What I Did

- Added scripts/_console.py to configure stdout/stderr with errors="replace", preserving their encoding and all stored Unicode data. Capture streams without reconfigure remain supported.
- Applied it before main in every printing Python CLI entry point in scripts/, covering task/handoff/YAML text, diagnostics, and other CLI output. Both direct script and package-module execution use the same helper. No CLI was executed merely because its entry point was modified.
- Added a forced PYTHONIOENCODING=cp1252 subprocess regression covering active/done/blocked task IDs, arrow and em-dash titles, and unchanged fixture contents. Added stream and CLI wiring tests.
- Added exactly the integration and this handoff path to POST_TEST_ALLOWLIST_EXACT; no other allowlist changes.

CLI entry points updated:

- scripts/agentic_os_memory.py
- scripts/allocate_worktree.py
- scripts/append_log.py
- scripts/approve_dispatch.py
- scripts/assignments.py
- scripts/check_cognee_profile.py
- scripts/cleanup_worktree.py
- scripts/create_handoff.py
- scripts/create_task.py
- scripts/disable_codex_canary.py
- scripts/execute_dispatch.py
- scripts/handoff_closeout_gate.py
- scripts/handoff_verification_block.py
- scripts/inspect_codex_cli.py
- scripts/inspect_worktree.py
- scripts/list_mcps.py
- scripts/list_roles.py
- scripts/list_skills.py
- scripts/list_tasks.py
- scripts/list_teams.py
- scripts/memory_extractors.py
- scripts/memory_librarian.py
- scripts/orchestrate_task.py
- scripts/prepare_codex_canary.py
- scripts/prepare_codex_canary_37b.py
- scripts/preview_codex_dispatch.py
- scripts/preview_dispatch.py
- scripts/run_claude_event_consumer.py
- scripts/run_claude_reviewer.py
- scripts/run_codex_builder.py
- scripts/run_codex_canary.py
- scripts/run_local_builder_worker.py
- scripts/run_orchestrator.py
- scripts/run_tests.py
- scripts/session_pickup.py
- scripts/sign_approval.py
- scripts/suggest_team.py
- scripts/sync_obsidian.py
- scripts/update_task.py
- scripts/validate.py
- scripts/validate_codex_activation.py
- scripts/verify_approval.py
- scripts/verify_codex_canary_package.py
- scripts/verify_repository_verification.py
- scripts/watch_assignments.py
- scripts/work_lock.py

## What Remains

- Commit from a Git-writable environment and generate committed-tip verification evidence. This sandbox exposes .git read-only; no commit was attempted.
- Receiver owns the full integration gating run. No full suite, session pickup, installation, push, merge, or network action was run.

## Decisions Made

- Replace unrepresentable output characters only; keep original task YAML and handoff content intact.
- Configure only CLI entry points, so importing modules does not change process-global streams.
- Cover every printing CLI conservatively to avoid missing indirect YAML-derived diagnostics.

## Open Questions

None blocking review.

## How to Verify My Work

python -m unittest tests.test_phase15_cli tests.test_console_encoding tests.test_cli_discovery tests.test_cli_guardrails tests.test_phase3_3_review_fixes.HandoffVerificationProtocolTests
python scripts/validate.py
git diff --check

## Verification Results

- Regression reproduced UnicodeEncodeError before the fix; passes after the fix.
- New regression/helper/wiring tests plus handoff verification: 19 tests, exit 0.
- Existing focused CLI run (tests.test_phase15_cli, tests.test_console_encoding, tests.test_cli_discovery, tests.test_cli_guardrails): 21 tests, exit 0, 293.865 seconds. This run loaded the initial one-test regression module; the separate 19-test run includes its two subsequently added helper/wiring tests plus 16 handoff verification tests. Total distinct tests: 39. The existing Phase 1.5 test module was unmodified.
- validate.py: exit 0 with existing deprecated event warnings, including a run after this handoff was added.
- git diff --check: exit 0. All 46 CLI diffs were checked against HEAD and contain only the helper wiring.
- Windows tempfile mode 0700 ACLs prevent fixture access in this sandbox. Focused unittest runs use a process-local os.mkdir wrapper substituting mode 0777 for 0700, without changing tests or production code. Initial normal regression run failed during fixture setup; the successful red/green runs used the wrapper.

## Risks / Caveats

Unrepresentable console characters become replacement characters on legacy encodings; UTF-8 output remains intact. Imported main() functions do not reconfigure caller streams. No committed-tip or full-suite evidence is claimed; existing runtime/unittest_last_run.txt was not overwritten. SHA fields below identify the unchanged checkout used for working-tree checks, not an implementation commit. remote_head_sha records the local base only and does not claim remote verification. Existing untracked task instructions and execution logs were preserved.

## Recommended Next Action for Receiver

Review and commit the scoped diff, rerun focused tests, generate committed-tip evidence, and perform the integration gating run with the registered integration handoff path.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-06-encoding
branch: agent/codex/T-M1-06-CLI-ENCODING
base_sha: 64d4da005c45e50155243afb403bc93852d54885
implementation_sha: 64d4da005c45e50155243afb403bc93852d54885
tests_commit_sha: 64d4da005c45e50155243afb403bc93852d54885
final_head_sha: 64d4da005c45e50155243afb403bc93852d54885
remote_head_sha: 64d4da005c45e50155243afb403bc93852d54885
git_status_clean: false
validator_commit_sha: 64d4da005c45e50155243afb403bc93852d54885
test_count: 39 distinct focused tests (working tree; across two passing runs)
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-06-CLI-ENCODING__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-06-encoding
