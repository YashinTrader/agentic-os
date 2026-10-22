# Handoff: T-M1-28-LEGACY-STATUS-TAKEOVER
**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review (working-tree delivery)
**Handoff Protocol:** v2

## What I Did
- Added explicit --adopt-legacy-status with required actor/reason, process inspection, durable audit intent/result, and a timestamp/token archive preserving the original status bytes.
- Serialized adoption against operators and current-version startup using operator/instance/control locks. Adoption never signals processes.
- Kept identity_state and identity-bearing startup semantics unchanged. Any root identity field, even null, excludes adoption. Legacy startup refusal names the adoption command.
- Updated deployment maintenance instructions and POST_TEST_ALLOWLIST_EXACT for this handoff.
- Added real owned-process adoption/start/refusal tests plus partial-identity, scan-error, root-selection, and gone-identity coverage.

## What Remains
Receiver review and commit-bound closeout. Git metadata is read-only in this session; no commit, push, merge, network, canonical-checkout, deployment-directory, or session_pickup action was performed.

## Decisions Made
psutil is imported only for adoption and declared in requirements.txt. The installed dependency was used without installation/network. Process command lines, cwd and environment determine explicit state-root/root selection. Unknown candidate roots and unreadable Python/runtime process details fail closed. Missing psutil also refuses. The original file is renamed only after the scan and durable audit intent succeed.

## Open Questions
None blocking local implementation review.

## How to Verify My Work
Run python runtime/dispatch/m1-28/verify_required.py tests.test_stop_supervisor tests.test_layer_supervisor tests.test_provenance_deploy_root tests.test_import_guard tests.test_console_encoding, then python scripts/validate.py and git diff --check.
The local fixture adapter replaces only tempfile.mkdtemp to inherit directory permissions, avoiding this Windows sandbox's inaccessible mode-0700 temporary directories. Test assertions are unchanged. Final result: 54 required tests passed in 77.067 seconds; validator exit 0; git diff --check passed. Final measured evidence follows below.

## Risks / Caveats
- Disable the legacy scheduler and validate/stop its owned tree first. Old releases do not participate in the new locks and could otherwise restart after the process snapshot.
- Candidates whose root cannot be resolved block adoption conservatively. Refusal preserves status. The process scan is read-only and is never termination authority.
- Working-tree tests are not commit-bound release evidence. No full-suite claim. Dependency audit was not run because network is forbidden.
- Initial direct unittest execution hit sandbox temporary-directory permissions. An initial CIM implementation was superseded after CIM access failed; its debug output is not final acceptance evidence.

## Recommended Next Action for Receiver
Review, commit in a writable Git session, regenerate commit-bound v2 evidence, then follow the authorized pre-T-M1-25 upgrade runbook separately.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-28-legacystatus
branch: agent/codex/T-M1-28-LEGACY-STATUS-TAKEOVER
base_sha: 543f455a1648098979af382bef5ea0ac269e4134
implementation_sha:
final_head_sha: 543f455a1648098979af382bef5ea0ac269e4134
remote_head_sha:
git_status_clean: false
validator_commit_sha:
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-28-LEGACY-STATUS-TAKEOVER__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-28-legacystatus

### Test Evidence

tests_commit_sha: 543f455a1648098979af382bef5ea0ac269e4134
test_count: 54
test_exit_code: 0
known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; installed dependencies used without changes to environment

Evidence applies to the uncommitted working tree based on tests_commit_sha,
not an implementation commit. Raw final output is runtime/dispatch/m1-28/required-final.txt;
focused final scan tests are runtime/dispatch/m1-28/scan-final.txt (3 passed).
An intermediate psutil suite had one intermittent failure in the existing
unresponsive forced-stop test (unverifiable root identity); the final suite was
rerun to check it. Earlier debug outputs are superseded by required-final.txt.

raw_output_sha256: 1bb5333788f695bf53cd8bb987aac771a36386cb0e82837e91744be6af17fc77
