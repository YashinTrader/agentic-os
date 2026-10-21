# Handoff: T-M1-14-STRUCTURED-CLASSIFICATION
**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted implementation)
**Handoff Protocol:** v2

## What I Did

- Replaced whole-output keyword classification with extraction of terminal provider error envelopes from JSON/JSONL and known CLI error channels. Successful exit 0 remains completed when no structured failure or bounded-turn signal is present.
- Recognize Codex turn.failed/error events, Grok and Claude result is_error/error/subtype fields, and Grok's anchored API error (status ...) diagnostic. Ignore tool_use/tool_result, assistant/item events, paths, and successful result narration, including on nonzero exits.
- Preserve deadline, launch-error, timeout precedence, required-MCP blocked_external, authentication/quota categories and retry-after eligibility. Required-MCP and retry parsing now see only filtered diagnostics. Unrecognized provider failures and unrelated nonzero exits become failed.
- Detect max turns from explicit terminal stop_reason/subtype/code or matching positive integer num_turns/max_turns fields, plus the CLI's nonzero stderr diagnostic. Incidental max-turns wording in structured error message text does not override a quota error.
- Added eight regression tests with subcases for clean recovery output, structured provider errors at exit 0 and nonzero, retry timestamps, maximum turns, unrelated failures, malformed event types, pretty JSON/JSONL, and MCP error-channel filtering.
- Added tests/fixtures/quota_recovery_drill_excerpt.txt preserving the abbreviated event fragments (including ellipses and wrapped path) supplied in TASK_INSTRUCTIONS.md, followed by the required narration. The full original live capture was not supplied. Valid tool/result JSON events are covered separately.
- Registered this exact handoff path in POST_TEST_ALLOWLIST_EXACT.

## What Remains

- Commit in an environment with writable Git metadata, rerun focused checks, and generate commit-bound closeout evidence. git add failed creating .git/index.lock with Permission denied. No commit or staged changes were created.
- Receiver owns broader integration review. Full-suite execution was explicitly prohibited.

## Decisions Made

- Treat failed-exit plain stderr as the CLI diagnostic channel; plain stdout narration never supplies quota/auth/retry signals. The specific anchored Grok API-status diagnostic is a known error channel.
- Parse JSON envelopes without recursively searching nested tool or assistant events. Only terminal error fields contribute diagnostics; successful result text is excluded.
- Preserve the existing exit_code=None behavior when no failure/deadline/launch signal exists.
- Existing fixture changes: tests/test_physical_agent_launcher.py::FailureClassifyTests.test_auth_and_quota_classification now emits a Codex turn.failed error envelope instead of plain stdout "usage limit exceeded; retry-after: 60". This fixture previously depended on forbidden stdout keyword matching; expected quota/retry behavior is unchanged. No fixtures in the other three required modules were changed.

## Open Questions

- None blocking working-tree review.

## How to Verify My Work

```powershell
python runtime/dispatch/m1-14/run_focused.py
python scripts/validate.py
git diff --check
```

The retained focused runner loads exactly tests.test_failure_classify, tests.test_builder_condition_retry, tests.test_physical_agent_launcher, tests.test_quota_probe, and tests.test_run_deadlines. It creates temporary fixture directories inside this clone with inherited Windows permissions and cleans them up with a resolved-path boundary check. Runtime runner/output files are ignored local artifacts. On an unrestricted machine the equivalent python -m unittest invocation can run those same five modules directly.

## Verification Results

- Initial new regression run failed as expected against the original classifier (16 subcase failures), reproducing false classifications and stdout-sourced retry timestamps.
- Initial direct focused run hit Windows temporary-directory permission errors; it is not passing evidence. A preliminary sandbox runner retained directories and therefore failed one quota-probe cleanup assertion; cleanup was corrected without changing that test.
- Focused final result: 77 tests, zero failures/errors, exit 0. Evidence: runtime/dispatch/m1-14/focused-tests.txt and summary.json.
- python scripts/validate.py: exit 0; pre-existing deprecated-event warnings only.
- git diff --check: exit 0.
- git add: exit 1, unable to create .git/index.lock (Permission denied).

## Risks / Caveats

- Provider CLIs are represented by local fixtures/fakes; no live API or network was used. New envelope formats require explicit support rather than scanning arbitrary output.
- This handoff describes working-tree tests. SHA fields identify the unchanged base checkout and do not claim an implementation commit exists. remote_head_sha is the locally recorded origin/HEAD, without fetching or pushing.
- No dependencies changed. No network dependency audit was run because network was forbidden and staging was blocked.
- Existing untracked TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log were preserved.
- No session pickup, full test suite, network, push, merge, credential change, or remote agent dispatch was performed. No unrelated full-suite verification artifact was overwritten.

## Recommended Next Action for Receiver

Review the diff and focused evidence, commit from a Git-writable environment, rerun the five focused modules and validator, then regenerate commit-bound v2 verification evidence before closeout.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-14-classify
branch: agent/codex/T-M1-14-STRUCTURED-CLASSIFICATION
base_sha: ce65cb29fbdcf25ef010e35dadb6725641bbaaee
implementation_sha: ce65cb29fbdcf25ef010e35dadb6725641bbaaee
tests_commit_sha: ce65cb29fbdcf25ef010e35dadb6725641bbaaee
final_head_sha: ce65cb29fbdcf25ef010e35dadb6725641bbaaee
remote_head_sha: ce65cb29fbdcf25ef010e35dadb6725641bbaaee
git_status_clean: false
validator_commit_sha: ce65cb29fbdcf25ef010e35dadb6725641bbaaee
test_count: 77 focused tests (working tree; not the full suite)
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-14-STRUCTURED-CLASSIFICATION__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-14-classify

## Correction: T-M1-14B-REAL-PROVIDER-FORMATS (2026-10-22)

- Preserved the existing uncommitted T-M1-14 implementation and launcher fixture change. Failed-exit plain non-JSON stdout now supplies provider diagnostics alongside stderr. Plain stdout/stderr remain ignored on successful exits; structured failure and bounded-turn behavior are retained.
- Added the authentication phrase `failed to authenticate`, covering Claude's expired OAuth output as well as the supplied 401 diagnostic.
- Structured error message strings already retain nested/escaped JSON after envelope parsing. The verbatim July Grok 402 sample now has explicit regression coverage; no recursive scanning of tool/item events was introduced.
- Added five fixture files in `tests/fixtures/real_provider_errors/`. The two Claude messages and Grok JSON are verbatim from the correction instructions. Those instructions describe, but do not provide literal captures for, Codex JSONL and successful narration; these two fixtures use representative text (the existing Codex usage-limit envelope and narration containing all four named phrases).
- Added mixed stdout/stderr coverage proving tool_result, agent_message, and item content stay excluded on failed exits, and plain-stdout maximum-turn coverage for failed versus successful exits. Updated the former plain-stdout quota assertion to expect blocked_quota as now required.
- The first correction run caught the missing `failed to authenticate` phrase (79/80 passed); that matcher was corrected before final verification.
- Final correction verification: 80 focused tests passed, zero failures/errors, exit 0, using the retained runner (all four requested modules plus the existing deadline module). Evidence: `runtime/dispatch/m1-14/focused-tests.txt` and `summary.json`. `python scripts/validate.py` and `git diff --check` also exited 0; validator warnings concern existing deprecated v1 events.
- Commit is unavailable under this session's explicit read-only `.git` permission. No staging/commit attempt, network, session pickup, full suite, push, or merge was performed.
