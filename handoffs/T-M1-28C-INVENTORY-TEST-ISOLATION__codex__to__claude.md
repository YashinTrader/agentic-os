# Handoff: T-M1-28C-INVENTORY-TEST-ISOLATION
**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review (working-tree delivery)
**Handoff Protocol:** v2

## What I Did
- Injected explicit inventory snapshots inside adoption CLI subprocesses, including empty inventories for success and partial-identity cases. Existing assertions remain unchanged.
- Kept one real-process legacy integration test. It spawns a decoy with an explicit state root, restricts enumeration to that owned PID, snapshots its real command line/cwd/environment/creation time, and injects the snapshot into adoption. Matching-root adoption refuses and leaves the decoy alive; adoption for a different temporary root succeeds while that same decoy remains alive.
- Changed root-resolution cases to inject immutable ProcessRecord fixtures and scan-error coverage to inject the inventory exception.
- Audited tests/ for inventory and legacy-adoption references. The remaining inventory tests in test_process_ownership_fencing already inject psutil.process_iter with fake processes, including inaccessible and disappearing candidates. No other unisolated adoption scans were found.
- Added this exact handoff path to POST_TEST_ALLOWLIST_EXACT. Product behavior is unchanged.

## What Remains
Receiver review and commit-bound verification. Git metadata is read-only in this sandbox; changes are delivered in the working tree.

## Decisions Made
CLI inventory patching runs in the child interpreter so the actual argument parser, adoption locks, archive and audit behavior remain exercised. Only the owned decoy is inspected in the integration test, preventing unrelated host processes from influencing its assertions.

## Open Questions
None blocking review.

## How to Verify My Work
Evidence is in ignored runtime/dispatch/m1-28c/. The local verify.py wrapper replaces tempfile.mkdtemp with os.mkdir using inherited permissions because the sandbox denies access inside mode-0700 temporary directories. It changes no assertions. No dependencies were installed and no network was used.

The additional working-tree impact regressions passed: 63 tests in 457.625 seconds (impacted-regressions.txt). The redundant initial combined run was stopped after split coverage was established; its incomplete required.txt is not acceptance evidence.

The required core modules passed: 39 tests in 315.718 seconds (core.txt). Three consecutive supervisor-module runs passed: 14 tests each (stop-2.txt, stop-3.txt, stop-4.txt). Validator exit 0 and git diff --check exit 0.

python scripts/impacted_tests.py --base 76adb36 exited 0 with no output because HEAD equals the base and this sandbox cannot commit Git metadata. The same selector applied to the working-tree diff selected tests.test_achievable_evidence_seal, tests.test_phase3_3_review_fixes, tests.test_phase3_4_1_integrity_closeout, tests.test_provenance_deploy_root and tests.test_stop_supervisor; see impacted.txt.

## Risks / Caveats
- The initial direct supervisor run failed during temporary-directory setup due to sandbox permissions, before assertions.
- The first wrapped supervisor run passed adoption coverage but encountered an unrelated transient heartbeat read (KeyError: pid) in test_restart_rollback_no_overlap_and_heartbeats_resume. Three subsequent consecutive complete runs passed (14 tests each; 56.675s, 56.455s, 52.933s).
- Evidence covers the working tree, not a tested implementation commit. No full-suite or remote-closeout claim.
- No session_pickup, canonical-checkout commands, network, push or merge was performed.

## Recommended Next Action for Receiver
Review the diff and commit in a writable Git session, then regenerate commit-bound v2 evidence before integration.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-28c-inventoryisolation
branch: agent/codex/T-M1-28C-INVENTORY-TEST-ISOLATION
base_sha: 76adb36747054847bf47fb4a27995af690b8ec02
implementation_sha:
tests_commit_sha: 76adb36747054847bf47fb4a27995af690b8ec02
final_head_sha: 76adb36747054847bf47fb4a27995af690b8ec02
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 144
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-28C-INVENTORY-TEST-ISOLATION__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-28c-inventoryisolation

### Test Evidence

known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; installed dependencies used

Measured working-tree acceptance evidence: 144 test executions (102 regression tests plus three 14-test supervisor runs), all exit 0.

core.txt sha256: 2aa21bc068dbd18692783205bf6dd8cc2fe70ee86efbf7f051b0d88158f4ab1f
impacted-regressions.txt sha256: 36b1461ec7c4dda6ba67782b325cbf2dfdc7aa217e6dddc4580bba123783a584
stop-2.txt sha256: 5c86562bcad452c965dee325d39e25ec3852d76b2f1422b92a1307c51784c309
stop-3.txt sha256: e7d3f6d1fb93f908b501b058767ebf7b256cd6e944ed2095185c33b1b1bb3455
stop-4.txt sha256: dcda5c8b9c639cbfdb34c01345952012fafc068e0f2742aa0bad80738d55f29c
impacted.txt sha256: df5e4eb9117173a62bac628bfc53f4809a03160dd08f92c3515fe0870a213a37
verify.py sha256: 415e10bf2b2059b9a27671b740c14e6b6ce0da0cd6a8bf7215888c93dd326d69
validate.txt sha256: 358dd588e059e7aec1ece947f86f9d6c4c642769d1fd3ef56699620fdaf7e01a
