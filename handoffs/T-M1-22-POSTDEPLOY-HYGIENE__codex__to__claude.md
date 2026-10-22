# Handoff: T-M1-22-POSTDEPLOY-HYGIENE

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted isolated working tree)
**Handoff Protocol:** v2

## What I Did

- Move cognee==1.1.0 from core requirements.txt to optional requirements-memory.txt. Document explicit memory installation and resolution of the core Cargo bootstrap blocker. Keep run_tests.py default core install and --skip-install unchanged. Update the profile dependency test and add an AST regression prohibiting Cognee imports across orchestrator/, dispatch/, and scripts/.
- Restrict consumer poke age and unhandled-poke alerts to assignment_completed events with source != claude. Add ignored_pending_poke_count for other notices. Processing eligibility and processing behavior remain unchanged.
- Make assignments, work_lock, and consumer_claims CLIs default to resolve_state_root: environment then own checkout. Explicit --root keeps its previous behavior, including an initially absent runtime directory. Select configuration through resolve_config_root and scope selected roots to the operation, restoring the caller environment afterward. Explicit legacy roots without a config override retain library configuration fallback. Configuration environment override takes precedence; fallback is the explicit legacy root or own checkout. Add precedence and configuration fallback regressions and deployment documentation.
- Batch all application import checks into one fresh interpreter. Clear project file-backed modules and application package namespaces between imports, retain third-party imports, run orchestrator.loaders first, and report every module's traceback. Assert batch duration below 60 seconds after completion. A synthetic circular-import regression verifies that a successful dispatch-first import cannot mask the loaders-first failure, and that subsequent module failures are still reported.
- Register this exact handoff path in POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review and commit-bound closeout in a Git-writable session. No implementation commit, sealed full-suite artifact, remote comparison, push, or merge is claimed. Blank implementation/tests/remote SHA fields below are intentional pending closeout values. The current HEAD is the task base, not a commit containing these changes.

## Decisions Made

Use the shared root_paths.operator_roots context manager to restore both root variables even on errors. Preserve explicit --root behavior instead of imposing the default resolver's existing-runtime validation on legacy explicit roots. Default state roots continue to use the shared resolver's validation. Cognee remains optional; its standard-library profile checker needs no installed memory backend.

## Open Questions

None for implementation. Default network dependency bootstrap must be confirmed separately where network installation is authorized.

## How to Verify My Work

The isolated fixture runner is runtime/postdeploy_test_runner.py. It redirects temporary directories into this clone using normal inherited directory permissions (this sandbox denies access to Python's mode-0700 temporary directories), retries read-only Git-object cleanup, and excludes .git and temporary fixture directories only when copying this repository for executor fixtures. Test assertions and application behavior are not patched by the runner.

- Final core group: 101 tests passed in 49.296 s, exit 0. Includes hygiene, Cognee profile, config roots, provenance deployment roots, consumer claims, review lease recovery, Claude event consumer, and console encoding. Evidence: runtime/dispatch/m1-22/final-core.txt.
- Final import guard and executor group: 7 of 8 tests passed, including the guard within 60 seconds and six executor tests. One executor fixture copy raced with relocation of a diagnostic capture; its assertion was not reached. The separate rerun passed (1 test, 12.136 s, exit 0): runtime/dispatch/m1-22/final-executor-rerun.txt. Group evidence: runtime/dispatch/m1-22/final-guard-executor.txt. The guard runs the actual orchestrator.loaders import first.
- python scripts/check_cognee_profile.py --json: exit 0, local profile accepted.
- python scripts/validate.py: exit 0 (existing deprecated-v1-event warnings only).
- git diff --check: exit 0.

109 unique tests covered across the focused and required groups. Earlier failed captures (temporary-directory permissions, read-only Git-object cleanup, initial import-guard timeout, CLI environment leakage, and diagnostic-file relocation during fixture copying) are superseded by the final groups; they are retained for diagnosis. No claim that scripts/run_tests.py or full unittest discovery passed is made. Existing provenance tests exercise mocked default-install and --skip-install paths; no network dependency installation was attempted.

## Risks / Caveats

Changes remain uncommitted; repository metadata is read-only in this isolated task. Verification is working-tree evidence, not commit-bound release attestation. Optional Cognee installation can still require Rust/Cargo. No commands were run against the canonical or deployment checkout; no network, session pickup, push, or merge was performed.

The initial direct unittest attempt (tool session 72325, capture postdeploy-tests.txt)
has not returned as of handoff. It uses the default temporary-directory behavior
and is not the verification evidence above. It was left untouched under the
no-process-killing instruction. Subsequent isolated fixture runs have completed.

## Recommended Next Action for Receiver

Review the diff, commit the implementation, and run the normal commit-bound closeout workflow with --skip-install when offline. Revalidate the handoff at the committed tip and fill the pending SHA/evidence fields. Keep external actions subject to separate authorization.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-22-postdeploy
branch: agent/codex/T-M1-22-POSTDEPLOY-HYGIENE
base_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
implementation_sha:
tests_commit_sha:
final_head_sha: 0680ccd010673ce4f6ff7c57df2925d133b6e63e
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 109
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-22-POSTDEPLOY-HYGIENE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-22-postdeploy
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: No network authorized; focused tests use existing core dependencies
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-22-postdeploy
