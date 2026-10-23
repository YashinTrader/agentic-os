# Handoff: T-M1-27B-STALE-MOCK

**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review

**Handoff Protocol:** v2

## What I Did

- Retargeted the state-root Git mock to orchestrator.process_ownership.owned_run, preserving the cwd == state-root assertion.
- Audited all tests for subprocess.run/Popen patches and patch.object equivalents in the eight specified modules. Retargeted three builder-condition negative-spawn mocks to owned_run; all original assertions remain. No other stale targets found.
- Added scripts/impacted_tests.py: --base REF [--head REF], or --base BASE..HEAD, prints sorted unittest module names for changed tests and direct imports/patch targets of changed Python modules. Handles from-package imports, patch decorators, keyword targets, and module boundaries. Added two selector tests and the required console-encoding entrypoint setup.
- Registered this handoff in POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver should commit the local changes and regenerate commit-bound evidence. No network or push performed.

## Decisions Made

Selection is static and direct, without transitive dependency expansion. Changed test modules are included themselves. Uncommitted changes are outside the requested Git range; the new selector test is run explicitly.

## Open Questions

None.

## How to Verify My Work

Focused checks: 20 tests passed. Initial broad run executed 370 tests with two failures: missing console setup in the new script, and a source scan encountering an aborted fixture copy. Console setup was fixed and the aborted fixture tree was moved to the permitted system temp directory. The 17-test affected-module recheck passed. Final clean run: all 370 tests passed (exit 0), including all 23 impacted modules for 543f455..HEAD plus tests.test_impacted_tests, tests.test_import_guard, and tests.test_console_encoding. Evidence: runtime/dispatch/m1-27b/tests-final.txt and test-final-exit-code.txt. validate.py passed (exit 0, existing deprecated v1 event warnings); git diff --check passed.

```powershell
$selected = @(python scripts/impacted_tests.py --base 543f455..HEAD)
python runtime/dispatch/m1-27b/run_offline.py -v @selected tests.test_impacted_tests tests.test_import_guard tests.test_console_encoding
python scripts/validate.py
git diff --check
```

Local evidence and the sandbox runner are in runtime/dispatch/m1-27b/ (Git ignored). The runner uses the permitted system temp directory, replaces Windows mkdir mode 0700 with inherited permissions, redirects the existing explicit C:/tmp fixture directory there, and excludes only .task-tmp plus runtime/dispatch/m1-27b diagnostic artifacts from checkout copies. Assertions and production code remain unchanged. Direct unittest invocation failed on sandbox temporary-directory permissions before reaching assertions. Earlier broad runs were interrupted through their own tool sessions while diagnosing temporary-directory access and recursive fixture copies; no tests are excluded from the final run.

## Risks / Caveats

- SHA fields below identify the existing HEAD; implementation is uncommitted. remote_head_sha is an unqueried protocol placeholder equal to HEAD. This is working-tree verification, not a committed seal.
- No session_pickup, command against the canonical checkout, network, dependency installation, dependency audit, or external action. Dependencies unchanged.
- Task-provided TASK_INSTRUCTIONS.md and Codex logs preserved. A sandbox-denied temporary directory from the initial direct invocation remains under .task-tmp/.

## Recommended Next Action for Receiver

Review and commit the changes, then regenerate verification evidence.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-27b-testfix
branch: agent/codex/T-M1-27B-STALE-MOCK
base_sha: 7ea872c4c0ebbf2c9076b7da84022803d22c97ae
implementation_sha: 7ea872c4c0ebbf2c9076b7da84022803d22c97ae
tests_commit_sha: 7ea872c4c0ebbf2c9076b7da84022803d22c97ae
final_head_sha: 7ea872c4c0ebbf2c9076b7da84022803d22c97ae
remote_head_sha: 7ea872c4c0ebbf2c9076b7da84022803d22c97ae
git_status_clean: false
validator_commit_sha: 7ea872c4c0ebbf2c9076b7da84022803d22c97ae
test_count: 370
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-27B-STALE-MOCK__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-27b-testfix
