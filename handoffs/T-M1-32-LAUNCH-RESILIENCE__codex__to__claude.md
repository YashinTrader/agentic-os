# Handoff: T-M1-32-LAUNCH-RESILIENCE
**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review (working-tree delivery)
**Handoff Protocol:** v2

## What I Did
- Added stdlib launch classification for the specified policy WinErrors, policy stderr markers, missing-executable errors and transient failures. Exit evidence and launch ownership records carry failure_class.
- Policy/config failures immediately open persistent child circuits. Recorded executable evidence includes resolved path, size, nanosecond mtime and SHA-256. Identity checks run no more than once/minute and reuse hashes when stat evidence is unchanged. Removing and restoring identical blocked bytes does not permit a security-policy probe.
- Added stable per-layer/path/hash alerts, a root parked alert, and audited single-use child reset tokens. Each executable identity gets one child alert; a fully blocked root additionally gets one separate root-park alert.
- Added injectable bounded jitter, transient circuits after six exits/600 seconds, and single half-open probes with 15-minute through four-hour exponential cooldowns. Persisted deadlines use Unix wall time and local scheduling uses monotonic time.
- Suppressed unchanged status writes; normal/parked liveness writes occur at 30/60 seconds. Heartbeat-only status changes batch at five seconds; failures, progress changes, state transitions and controls remain immediate. Loop cadence is 1 second normally, 0.25 while starting, 5 while parked.
- Added a durable root-start guard, enabled by run_supervisor_layers, inside the existing instance/control startup locks. The fourth start/30 minutes returns 78; cooldown doubles from 30 minutes to eight hours. Ten minutes with both children running clears the budget. Completed planned stops remove their own start from the crash budget.
- Added operator commands: stop_supervisor --reset-circuit <layer> --actor --reason; run_supervisor_layers --reset-root-guard --actor --reason. Both use operator/control locks and durable audit intent/outcome records.
- Added docs/RUNTIME_FAILURE_POLICY.md, deterministic resilience tests, and updated existing fixtures for conditional writes and the constructor guard option. Registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## What Remains
Receiver review and commit in a writable Git session. No deployment or scheduler configuration change was performed.

## Decisions Made
- Keep the root alive when parked so the Scheduled Task sees the existing root. Alerts are local durable JSON artifacts, not remote notifications.
- Blocked executable evidence remains the original denial identity; an in-memory stat cache avoids repeated hashing after metadata-only changes without losing the original SHA-256 comparison.
- Preserve existing process ownership and graceful stop fencing. A successful Popen still requires a valid heartbeat to become running.
- Deliver an uncommitted working tree as explicitly requested. Commit-bound verification fields are left blank rather than claiming that the base SHA contains these changes.

## Open Questions
None.

## How to Verify My Work
All test Python commands used C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe, with installed dependencies and no network or installation. Logs are in runtime/dispatch/m1-32/ (ignored local evidence). PowerShell renders unittest stderr as NativeCommandError text even on successful tests; exit codes below are the captured Python LASTEXITCODE values.

| Command arguments after the signed interpreter | Tests | Exit code | Log |
| --- | ---: | ---: | --- |
| -m unittest tests.test_launch_resilience tests.test_layer_supervisor | 42 | 0 | resilience-tests.txt |
| -m unittest tests.test_stop_supervisor | 16 | 0 | stop-tests.txt |
| -m unittest tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root tests.test_config_root | 46 | 0 | guard-tests.txt |
| -m unittest tests.test_achievable_evidence_seal tests.test_phase3_3_review_fixes tests.test_phase3_4_1_integrity_closeout | 63 | 0 | verification-tests.txt |
| scripts/impacted_tests.py --base b4aee5f | n/a | 0 | no selected modules: HEAD equals base |
| scripts/validate.py | n/a | 0 | validate.txt |
| git diff --check | n/a | 0 | clean |

The impacted selector only sees committed changes. I also selected direct importers against all changed/new Python paths using its impacted_tests helper: achievable_evidence_seal, config_root, launch_resilience, layer_supervisor, phase3_3_review_fixes, phase3_4_1_integrity_closeout, provenance_deploy_root and stop_supervisor; all appear above.

Tests cover a 24-hour unchanged policy denial with one launch; stderr markers; identity-change success and renewed denial; hash reuse; missing executable recovery; audited reset consumption; transient jitter bounds and at most 16 launch attempts/day; persisted transient probe deadlines; healthy and parked 600-step write budgets; continuously ticking idle children (120 writes/600 seconds); parked CPU under two CPU seconds for 600 complete iterations (3000 simulated seconds); root cooldown doubling/cap; root return 78; healthy reset; planned-stop exemption; CLI audit requirements; and parked stop-request acknowledgement. Existing real-process shutdown and ownership tests also pass.

## Risks / Caveats
- Working-tree test evidence only; no full-suite or commit-bound verification claim. No environment-blocked tests remain in the final runs.
- Earlier runs truthfully returned 1: the new regression reproduced six launches instead of one; the existing atomic-write test needed a content mutation; the stop fixture needed to forward the new constructor keyword; a new reset CLI fixture needed its runtime directory. Those fixtures and product behavior were corrected, then affected suites rerun. An attempted tests.test_repository_verification command also returned 1 because that module does not exist; the three actual direct-importing verification modules passed instead.
- Before reading TASK_INSTRUCTIONS.md, I followed the supplied mandatory session-start rule and attempted the main-checkout session_pickup using the default interpreter. It exited 1 with PermissionError while creating an assignment claim. This conflicted with the subsequently read isolated-clone task instructions. No assignment was claimed; there were no further main-checkout actions. All task Python after that used the specified signed runtime.
- Executable replacement detection intentionally uses size/mtime before hashing, as specified. Changes preserving both metadata values cannot be detected without an audited reset. Alerts are deduplicated per identity and retained for operator review.

## Recommended Next Action for Receiver
Review the working-tree diff and local evidence, commit the scoped files, regenerate commit-bound v2 evidence, then integrate through the normal review gate.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-32-launch-resilience
branch: agent/codex/m1-32-launch-resilience
base_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
implementation_sha:
tests_commit_sha:
final_head_sha: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 167
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-32-LAUNCH-RESILIENCE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-32-launch-resilience
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; installed vendored dependencies used
