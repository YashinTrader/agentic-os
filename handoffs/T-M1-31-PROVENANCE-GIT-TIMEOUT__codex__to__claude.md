# Handoff: T-M1-31-PROVENANCE-GIT-TIMEOUT

From: codex
To: claude
Date: 2026-10-23
Status: review; uncommitted working tree

## Implementation

- `root_paths.py`: named 30-second Git timeout, one retry on timeout (at most two attempts), non-fatal failure reasons in `config_root_git_sha_error`, and process-local success-only cache keyed by resolved config root. Success metadata retains its existing shape. Missing `.git`, missing Git, nonzero Git status (first stderr line), persistent timeout, empty output, and other subprocess errors retain a reason.
- `tests/test_root_paths_provenance.py`: seven regressions covering retry, persistent timeout and no failure caching, missing Git, per-root success caching, nonzero return/recovery, missing `.git`, and empty output.
- `scripts/repository_verification.py`: registered this exact handoff in `POST_TEST_ALLOWLIST_EXACT`.

## Verification

All task Python commands used `C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe` after reading the task. No dependencies installed.

- Required suite: `-m unittest tests.test_root_paths_provenance tests.test_config_root tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root`: **53 tests, OK, true exit 0**, 634.119 seconds.
- `scripts/impacted_tests.py --base b4aee5f`: true exit 0, no modules (changes are uncommitted). Additional direct-importer coverage selected using `scripts.impacted_tests.references` and `impacted_tests`; results below will be finalized when the active run exits.
- `scripts/validate.py`: true exit 0 both before and after allowlist registration; existing deprecated event-log warnings only.
- `git diff --check`: true exit 0; line-ending conversion warnings only.

## Caveats and receiver actions

No commit, push, network, dependency install, or deployment. Receiver must review and commit the working-tree changes and regenerate commit-bound evidence. The task branch/base are `agent/codex/m1-31-provenance-timeout` / `b4aee5f`.

Before reading TASK_INSTRUCTIONS.md, the earlier mandatory session rule caused a canonical-checkout session-pickup attempt using its default interpreter. It failed with exit 1 on PermissionError creating an assignment claim; no assignment was claimed. No further canonical-checkout work was performed.

Command setup errors: two initial quoted cmd.exe Python launches exited 1 before running Python; corrected invocations are recorded above. An attempted `tests.test_repository_verification` run exited 1 because that module does not exist; correct dependency-selected verification tests were then launched. A temporary helper write/delete reported errors, but subsequent file inspection confirmed the helper does not exist. A read-only process inventory was denied by the environment. These are not passing test results.
