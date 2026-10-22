# Handoff: T-M1-17-CONFIG-ROOT

**From:** codex
**To:** claude
**Date:** 2026-10-22
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Added dispatch/roots.py as the shared configuration/state selector. Deployment configuration defaults to the entrypoint code checkout; --config-root overrides AGENTIC_OS_CONFIG_ROOT. Explicit/environment config roots and entrypoint defaults require agents/ and config/. State roots require only runtime/. scripts/state_root.py retains its compatible import.
- Routed adapter/adapter-registry reads, execution policy (including work-lock concurrency), wake configuration, quota-probe authorization, deadlines, orchestrator registries, registry CLIs/team suggestions, and dashboard registry readers through the selector. Reviewer prompts/schema are code constants; no runtime prompt/schema disk loader was found in dispatch/orchestrator.
- All three layer entrypoints export both selected roots. The parent passes both CLI flags and environment variables to both children. The minimal agent environment preserves both non-secret root variables. Existing inherited environments cover probes and reviewer launches.
- Kept runtime runs/locks/queues, logs, task lookup, handoffs, Git operations and worktree allocation rooted in the target/state repository. Worktree placement retains the existing sibling/override behavior.
- Added configuration path, local configuration HEAD SHA, and state path to parent, builder, and consumer status. SHA is null for non-Git roots or failed Git lookup. Persistent builder startup refreshes provenance even with an existing status; standalone ticks also record it.
- Added seven offline regression tests, deployment/state-root documentation in docs/DEPLOYMENT_ROOTS.md, and this exact handoff path to POST_TEST_ALLOWLIST_EXACT.

## What Remains

Receiver review, commit from a Git-writable session, commit-bound verification, and deployment.

## Decisions Made

Configuration follows the deployed code checkout; mutable state and target Git operations follow the state root. Legacy library callers retain their repository default, while deployment roots are validated before either layer starts.

## Open Questions

None blocking local review.

## How to Verify My Work

Final focused run: 190 discovered, 187 passed, 3 skipped, zero failures/errors, exit 0. Evidence: runtime/dispatch/m1-17/focused-tests.txt and summary.json.
The command is:

```powershell
python runtime/dispatch/m1-17/run_focused.py test_config_root test_windows_write_contention test_prelaunch_failure_isolation test_work_lock test_builder_condition_retry test_physical_agent_launcher test_process_ownership_fencing test_quota_probe test_failure_classify test_run_deadlines test_layer_supervisor test_mcp_isolation test_phase3_5_codex_context
python runtime/dispatch/m1-17/run_supplemental.py test_config_root
python scripts/validate.py
git diff --check
```

The supplemental run checks the latest dashboard changes and passes all 7 tests, exit 0.
Validator passes, exit 0, with existing deprecated event-log warnings only. Registry CLI JSON smoke checks pass for roles, skills, MCPs, and teams. Diff whitespace check passes.

Three real-process termination tests are deliberately skipped because TASK_INSTRUCTIONS.md forbids killing processes: ProcessOwnershipTests.test_real_grandchild_terminated, LayerSupervisorTests.test_shutdown_terminates_owned_tree, and LayerSupervisorTests.test_real_dummy_crash_restarts_with_bounded_stderr_and_recovery. Mocked lifecycle tests run normally.

## Risks / Caveats

- .git is explicitly read-only in this session. No staging/commit attempt was made. All SHA fields below refer to the unchanged base checkout, not an implementation commit. Receiver must commit the reviewed diff and regenerate commit-bound verification.
- Local repository verification was invoked with `--canonical-repo .` to avoid the forbidden canonical checkout. It exited 1 against the preserved integration artifact: commit, test count, raw-output hash, and evidence metadata differ. The initial handoff also lacked four mandatory section headings; these were added and validation was repeated. The final retry reports Validator at HEAD passed, exit 0; artifact verification remains failed. See runtime/dispatch/m1-17/final-closeout-verification.txt.
- Tests are focused working-tree evidence. runtime/unittest_last_run.txt is preserved; it is an older integration artifact, not this run. The repository closeout gate cannot establish commit-bound verification from that artifact and this uncommitted diff.
- Initial broad tests exposed a sandbox harness issue: putting fixtures inside a copied source tree caused recursive copying. That run failed in optional registry fixtures; the final runner uses ignored runtime/__pycache__/ fixture directories. Failed output is retained separately. A second, nonrecursive full-checkout registry run was discontinued because repeated checkout copying was excessive; it ended with fixture setup errors after its fixture path was retired. It is not counted as passing verification; final task verification excludes those optional suites and covers registry selection directly plus CLI smoke checks. A fixture-source rename and stop file ended the bad copy traversal through normal filesystem errors; no process was terminated. Python 3.11 private temporary-directory ACLs are bypassed only in the local runner by using inherited permissions, never in production. An earlier direct unittest attempt could not access its OS temporary directories and produced fixture setup errors.
- Before the isolated task exception was known, the general AGENTS instruction triggered one canonical-checkout session_pickup attempt. Claim creation failed with PermissionError; no assignment was claimed. No further canonical-checkout action was taken.
- No push, merge, network, dependency install/audit, paid probe, credential change, or process termination was performed. Dependencies were unchanged. Existing TASK_INSTRUCTIONS.md, codex_stdout.jsonl, and codex_stderr.log are preserved.
- Provenance reports Git HEAD and cannot attest to a dirty config tree. Deploy clean pinned checkouts. Existing legacy library fixtures may omit full config directories; fail-fast validation is mandatory at deployment entrypoints and for explicit/environment-selected config roots.

## Recommended Next Action for Receiver

Review the local diff, commit from a Git-writable session, regenerate commit-bound v2 evidence, then deploy the pinned checkout with --state-root pointing at the target repository. Confirm all three status files show the pinned config SHA and target state path.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-17-configroot
branch: agent/codex/T-M1-17-CONFIG-ROOT
base_sha: a9d0db7c892f21985320de953e157c874454da52
implementation_sha: a9d0db7c892f21985320de953e157c874454da52
tests_commit_sha: a9d0db7c892f21985320de953e157c874454da52
final_head_sha: a9d0db7c892f21985320de953e157c874454da52
remote_head_sha: a9d0db7c892f21985320de953e157c874454da52
git_status_clean: false
validator_commit_sha: a9d0db7c892f21985320de953e157c874454da52
test_count: 190
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-17-CONFIG-ROOT__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-17-configroot
known_exempt_failures: []
raw_output_sha256: 0f5d3a4eccd7a8586fdfd5fb660571f1bcd1ed6fdc6ed03855db74635dfe667e
repo_identity: {"origin": "https://github.com/YashinTrader/agentic-os.git", "roots": ["18ccb6e2e421044e6e21411c83513d80e38fb4ba"]}
dependency_install: skipped
dependency_install_reason: Task forbids network; dependencies unchanged; installed local environment used
artifact_origin_path: C:/Users/gabot/agentic-os-worktrees/m1-17-configroot
hostname: AIAG
python_version: 3.11.15
command_line: ["C:\\Users\\gabot\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe", "runtime/dispatch/m1-17/run_focused.py", "test_config_root", "test_windows_write_contention", "test_prelaunch_failure_isolation", "test_work_lock", "test_builder_condition_retry", "test_physical_agent_launcher", "test_process_ownership_fencing", "test_quota_probe", "test_failure_classify", "test_run_deadlines", "test_layer_supervisor", "test_mcp_isolation", "test_phase3_5_codex_context"]
timestamp: 2026-10-22T04:52:32.022104+00:00
python: C:\Users\gabot\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
