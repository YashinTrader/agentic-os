# Handoff: T-M1-26-GROK-STREAMING-ACTIVITY

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Changed the composer launcher and adapter config to streaming-json, preserving --single, --cwd, and --max-turns. Reject buffered output overrides.
- Count every typed Grok NDJSON event as progress. Persist nonempty line liveness separately; malformed lines cannot establish startup or extend inactivity. Overall deadlines remain bounded.
- Require exit 0 plus a stdout end event for completion. Missing terminal evidence and unknown exit status fail without automatic retry. Preserve existing nonzero exit and provider classification rules.
- Persist end.sessionId, end.stopReason, and provider input/output/total usage in supervisor_run.json and result.json.
- Feed top-level streaming error diagnostics and error stopReason into existing quota/auth/provider classification. Preserve nested 402 handling and ignore assistant/tool narration.
- Added a format-sensitive fake Grok regression that streams beyond both startup and inactivity windows. Existing silent-process regressions remain effective. Added captured-stream parsing, malformed-line liveness, terminal-evidence, and synthetic error-envelope regressions.
- Updated successful test doubles to emit terminal evidence. Added docs/GROK_STREAMING_ACTIVITY.md and this exact path to POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review and commit in a Git-writable session, followed by commit-bound verification. No implementation work remains.

## Decisions Made

Grok activity is adapter-specific; existing Codex and Claude reviewer activity semantics and launch formats are preserved. Quota probes retain their separate bounded JSON protocol. Provider total_tokens is stored as reported rather than recomputed, because it includes additional accounting in the captured fixture.

## Open Questions

Real streaming error envelopes remain unverified. Supported type:error error/message/data envelopes and type:end error stopReason envelopes are defensive interpretations; the tests reuse the captured nested 402 diagnostic within explicitly synthetic envelopes. No new provider error strings or network observations were invented.

## How to Verify My Work

135 tests passed across the requested focused modules, console encoding, and dispatch executor: 125 focused plus 10 console/executor. One process-ownership test was deliberately excluded because it launches and terminates a real child/grandchild, contrary to the task prohibition. All remaining ownership/fencing tests ran. A final 15-test streaming/classification run passed after the last diagnostic extraction change. validate.py passed with exit 0 and existing deprecated event-field warnings. git diff --check passed.

Evidence: runtime/dispatch/m1-26/focused-final.txt, console-executor.txt, classification-final.txt, validate-final.txt. Earlier core/focused captures contain corrected failures and are not final evidence.

```powershell
python runtime/dispatch/m1-26/run_offline.py tests.test_grok_streaming tests.test_physical_agent_launcher tests.test_run_deadlines tests.test_failure_classify tests.test_process_ownership_fencing tests.test_windows_write_contention tests.test_prelaunch_failure_isolation tests.test_builder_condition_retry tests.test_quota_probe
python runtime/dispatch/m1-26/run_offline.py tests.test_console_encoding tests.test_dispatch_executor
python runtime/dispatch/m1-26/run_offline.py tests.test_grok_streaming tests.test_failure_classify
python scripts/validate.py
git diff --check
```

The offline runner excludes only test_real_grandchild_terminated, places temp fixtures under this clone, uses inherited directory permissions to avoid sandbox Windows 0700 ACL failures, and excludes runtime/.git/transcripts from root repository copies. Production assertions are unchanged. The console/executor capture says OK (10 tests); its earlier PowerShell stderr redirection surfaced NativeCommandError despite unittest success. The final runner writes results to stdout, allowing an unambiguous exit 0.

## Risks / Caveats

- Streaming error shapes need captured production fixtures before claiming provider-format verification.
- Git metadata is read-only here. All SHA fields below identify unchanged base HEAD, not a committed implementation. remote_head_sha is a protocol placeholder equal to local HEAD; no remote was queried. Receiver must commit and regenerate commit-bound evidence.
- The excluded real termination test should be run in a session permitting process termination. Fake-process termination behavior was verified locally.
- No session_pickup, canonical/deploy checkout command, network, Grok invocation, process killing, push, merge, credential change, or dependency installation. Dependency audit omitted because network is forbidden and dependencies are unchanged.
- Task-provided TASK_INSTRUCTIONS.md, codex_stdout.jsonl, codex_stderr.log, and captured fixture are preserved. Runtime evidence is Git-ignored.

## Recommended Next Action for Receiver

Review the fake format-sensitive reproduction and captured stream, commit, regenerate commit-bound verification, and run the excluded process-termination case only where authorized.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-26-grokstreaming
branch: agent/codex/T-M1-26-GROK-STREAMING-ACTIVITY
base_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
implementation_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
tests_commit_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
final_head_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
remote_head_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
git_status_clean: false
validator_commit_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
test_count: 135
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-26-GROK-STREAMING-ACTIVITY__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-26-grokstreaming
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; dependencies unchanged
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-26-grokstreaming
