# Handoff: T-M1-25B-STATUS-READ-RACE
**From:** codex
**To:** claude
**Date:** 2026-10-23
**Task Status After Handoff:** review (working-tree delivery)
**Handoff Protocol:** v2

## What I Did
- Added read_control_status with a three-second monotonic deadline and 50 ms polling. Empty/malformed/non-object JSON and OS read errors are retried through read_heartbeat; incomplete root identities also wait before refusal.
- Used the bounded reader for initial stop identity, recorded-tree refresh, and final stop acknowledgement. Existing identity verification, Job membership, force termination, and refusal rules are unchanged.
- Made test status reads wait for the ready supervisor PID and start time. Startup waits for a new published identity and ticking children. The Windows Python launcher can have a different PID from the interpreter publishing status.
- Added deterministic coverage for empty, invalid, non-object JSON, sharing violations, bounded missing/legacy/partial identities, and refusal without force.
- Registered this exact handoff path in POST_TEST_ALLOWLIST_EXACT.

## What Remains
Receiver review. Git metadata is read-only in this sandbox; delivery is in the working tree.

## Decisions Made
Read retries do not cache an identity or make an unverifiable process safe to kill. A genuinely absent or incomplete identity still reaches the original refusal after the bounded wait. Adoption retains its existing locked legacy-status read.

## Open Questions
None.

## How to Verify My Work
Offline verification uses runtime/dispatch/m1-28c/verify.py, inherited from the prior task. It replaces tempfile.mkdtemp with os.mkdir using inherited permissions because sandbox access is denied inside Python's mode-0700 temporary directories. Test assertions and product behavior are unchanged by the wrapper.
Evidence and per-run timings: runtime/dispatch/m1-25b/.

## Risks / Caveats
- Working-tree evidence, not commit-bound verification; no full-suite claim.
- Initial direct runs failed in temporary-directory setup before assertions. The first wrapped full run exposed the launcher's differing PID; the helper was corrected before stability verification.
- Stop operations can spend up to three seconds per transient status read before continuing or refusing.
- No session_pickup, canonical-checkout commands, network, dependency installation, push, or merge.

## Recommended Next Action for Receiver
Review and commit in a writable Git session, then regenerate commit-bound v2 evidence before integration.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-28c-inventoryisolation
branch: agent/codex/T-M1-25B-STATUS-READ-RACE
base_sha: 7e6867bbb95f3e1cacc07f42255fe722003fdaf5
implementation_sha:
tests_commit_sha: 7e6867bbb95f3e1cacc07f42255fe722003fdaf5
final_head_sha: 7e6867bbb95f3e1cacc07f42255fe722003fdaf5
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 277
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-25B-STATUS-READ-RACE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-28c-inventoryisolation

### Test Evidence

known_exempt_failures: []
dependency_install: skipped
dependency_install_reason: Network forbidden; installed dependencies used

Accepted final-code stability evidence: runs 2 through 16, 15 consecutive runs of 16 tests, all exit 0 (240 test executions). Run 1 passed but preceded the final startup snapshot adjustment and is excluded from this count.

| Accepted run | Process elapsed seconds | Exit code |
|---|---:|---:|
| 1 (log stop-2.txt) | 45.625 | 0 |
| 2 (log stop-3.txt) | 42.843 | 0 |
| 3 (log stop-4.txt) | 45.344 | 0 |
| 4 (log stop-5.txt) | 52.938 | 0 |
| 5 (log stop-6.txt) | 49.109 | 0 |
| 6 (log stop-7.txt) | 52.328 | 0 |
| 7 (log stop-8.txt) | 45.422 | 0 |
| 8 (log stop-9.txt) | 51.265 | 0 |
| 9 (log stop-10.txt) | 43.875 | 0 |
| 10 (log stop-11.txt) | 48.859 | 0 |
| 11 (log stop-12.txt) | 49.218 | 0 |
| 12 (log stop-13.txt) | 55.875 | 0 |
| 13 (log stop-14.txt) | 49.218 | 0 |
| 14 (log stop-15.txt) | 49.672 | 0 |
| 15 (log stop-16.txt) | 48.188 | 0 |

Stability elapsed total: 729.779 seconds; range 42.843 to 55.875 seconds.

Required additional modules: tests.test_layer_supervisor, tests.test_process_ownership_fencing, tests.test_import_guard, tests.test_console_encoding: 37 tests, exit 0, 36.500 seconds process elapsed. Combined accepted test count: 277.

Validator: python scripts/validate.py, exit 0. git diff --check: exit 0.

SHA-256 evidence:
- timings.json: 7c68eb58ead3264376ba1aa4998fede5a6b8d239d922aebb16912f5c97ca8125
- required.txt: e251073ccc568c0bb4864dadbb7c2c136cf4c2eb762b330fa32f58cd4b8bb251
- stop-2.txt: ba8147d5cba186d0b602539bb006e8726c5d7e8db3b3dc6cf258536244ff641a
- stop-3.txt: e4fccbc03d5d2df29a3dee9d48d4d032295dc655103298adc66faa29c1fb9f0e
- stop-4.txt: 7ca74efb7f2ba0cbd2bf187530133d74e419e77fccbae7acd470e0793856ecdd
- stop-5.txt: df8385ee092e6463e7f2a406dce57609f7bf409c05238880323ab641a3d99778
- stop-6.txt: 972918ae583e253ca857df2998fad2579b5660a0d99efbd5d2f3553ef2581367
- stop-7.txt: a2c5938dd311c17757f1ed2af8e6640d37d9c21a34fa5274c4399230d4e3eace
- stop-8.txt: 16790704746ad13eaa7c26523b8a76ffc0911b8613465aa59373ddaf1d8c3bb3
- stop-9.txt: 3972ffc550869ac2cf55da3f5cd58bfbf25b671b9462c2faa588b070d61de1fb
- stop-10.txt: 30bd8a08577fcdd178bc7f123ea53cf20c423be094fa07b647ea0b2f7e7d96aa
- stop-11.txt: ff4b1527f2676ab4f65a5e2780eb479b2556834c80ce84aea22db11ade130bba
- stop-12.txt: af6e636087c48ca1b9be9a79745ca3676934747cf564ad2dad30b30bf8d7d0fe
- stop-13.txt: 17b2bdd14a7bb94ebf8efb386b02188ae940cf4e04328f88b2b22d0653adf9ea
- stop-14.txt: 02381c0170e39964209360cf4d935b0283f1c2c6392642141de6f639d3c1aeca
- stop-15.txt: 9e76e81d0fd6eca5157c642304996ed6cb80bc467d1543013063c1275aca297a
- stop-16.txt: b09363511481218f7fd5d19291d67beeaa4f28cd2a33fc5f65f69cf375ac234d
- verify.py: 415e10bf2b2059b9a27671b740c14e6b6ce0da0cd6a8bf7215888c93dd326d69
