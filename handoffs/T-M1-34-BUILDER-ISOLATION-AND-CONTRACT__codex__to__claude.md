# Handoff: T-M1-34-BUILDER-ISOLATION-AND-CONTRACT

**Handoff Protocol:** v2
**From:** codex
**To:** claude
**Date:** 2026-10-25
**Task Status After Handoff:** blocked

## What I Did

- Added a fail-closed Windows launcher using a fresh write-restricting SID, disabled privileges, Low integrity, Low-labelled clone/profile, explicit inherited pipe handles, and suspended process admission to a kill-on-close Job. Job ownership is separate from filesystem enforcement.
- Added standalone supervisor clones with independent Git metadata and objects using init plus local bundles (the installed clone frontend invokes a blocked MSYS shell), preserving T-M1-30 names, plus supervisor result import with untrusted Git config reset and a fresh empty hooks directory.
- Added task-contract schema validation, local task YAML/JSON/Markdown, supervisor SHA-256 receipt, ignored-artifact checks, required-file refusal, relative prompts, AGENTS.md exemption, environment isolation and all four CLI guards.
- Added state mutation comparison, outside-path stream detection, one progress checkpoint at turn 12 of 30, terminal diagnostics, and isolated completion/acceptance checks. The Grok default stays 30 turns.
- Added real adversarial OS fixture, setup-fault refusal tests, contract/CLI/env tests, evidence replay and supervisor mutation regressions. Updated existing fake workspace fixtures for the launch contract.
- Documented implementation, limitations and host evidence in docs/BUILDER_ISOLATION.md.

## What Remains

- PRIMARY BLOCKER: the real launcher cannot create its fresh restricted token in this execution environment. CreateRestrictedToken returns WinError 87 before labelling or process creation. The required adversarial test therefore fails; write-denial and allowed-write behavior have NOT been demonstrated. This is not an accepted isolation boundary yet.
- Run that test using the intended supervisor token. Do not replace the fresh SID with Everyone or fall back to an unrestricted process. The exact outer-token policy remains unconfirmed.
- Installed Grok help/profile/deny syntax and isolated authentication remain unverified. This session permits only the current checkout and signed runtime; no installed CLI executable or help was copied into the permitted area. No sandbox profile is enabled. Deny patterns in the plan are candidates requiring installed-version verification.
- The separate legacy dispatch/local_builder_core.py production route does not yet provision this contract/hash and is refused by the shared gate. Migrate that route and its post-build subprocesses before enabling it; no bypass was added.

## Decisions Made

- Refuse launch on token, label, shared-metadata or contract failures. Do not count a mocked denial or a skipped fixture as real boundary evidence.
- Use a fresh write-restricting SID in addition to MIC so unrelated Low directories are not writable merely because they are Low. Only the clone and its contained private profile are provisioned writable.
- Keep supervisor log files behind pipe relays. Run untrusted acceptance code under the same boundary. Copy no user auth/profile secrets.
- Treat exhausted turn budgets as reviewable failure with diagnostics, rather than granting another budget or reporting success.
- Leave T-M1-33's dispatch/work_lock.py, retry/dead-letter implementation and launch-failure classification unchanged. The supervisor classification override for exhausted budgets is strictly required by this contract; the isolation changes use existing lock paths and alert APIs.

## Open Questions

- Does the intended supervisor token permit adding the fresh restricting SID and creating the Low primary process without elevation?
- Which installed Grok deny grammar/profile is supported, and can it authenticate with the private profile while preserving isolation?

## How to Verify My Work

Use only C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe. TEMP/TMP must point to the checkout's __pycache__/m1-34-temp so legacy repository-copy tests exclude their own temporary trees.

- Run tests.test_builder_isolation_contract, tests.test_builder_watch and tests.test_builder_supervisor_contract. The first module intentionally returns nonzero if the real boundary cannot be exercised.
- Final affected-module and guard-pack module list: runtime/m1-34-validation/final-test-modules.json; output: runtime/m1-34-validation/final-tests.txt; actual exit: runtime/m1-34-validation/final-test-exit.json.
- Run scripts/validate.py and git diff --check.

## Verification Results

- Guard pack plus tests.test_launch_resilience: 59 tests, exit 0 (runtime/m1-34-validation/guard-pack.txt).
- Focused rerun: 79 tests, 78 passed, one failure, exit 1. Only tests.test_builder_isolation_contract.WindowsBoundaryTests.test_real_adversarial_builder_and_descendants failed: failed_launch: restrict token: [WinError 87] The parameter is incorrect.
- Host token query confirms IsTokenRestricted=true, TokenHasRestrictions=1 and four restricting SIDs; runtime/m1-34-validation/host-token-evidence.json records the real query. No token or system policy was changed.
- Real setup fault checks: 2 tests, exit 0. These inject setup faults and are not write-denial evidence. The adversarial fixture uses real APIs and no boundary mocks.
- Combined required/affected run: 29 modules, 413 tests, 3 failures, exit 1 (runtime/m1-34-validation/final-tests.txt). Failures were the required OS proof, the pre-existing timeout probe (marker absent before its 3-second timeout), and standalone Git clone transport (MSYS CreateFileMapping Win32 error 5).
- Timeout probe rerun alone: 1 test, exit 0 (probe-rerun.txt). The combined failure is retained, not erased or waived. A classification test also passed when rerun; an interim status-marker guess incorrectly identified it as the third failure, but the completed traceback identifies clone transport.
- Clone transport was corrected to native Git init plus local bundle fetch/import with file-only protocol and clean Git configuration. Even --local cloning still invoked the installed MSYS shell, so the clone frontend is no longer used. Real clone/import regression: 1 test, exit 0 (bundle-clone-proof.txt). Earlier local-clone attempts and trace remain recorded with exit 1.
- Final dependency rerun after the transport correction: 7 modules, 56 tests, 55 passed, only the required real OS proof failed, exit 1. Recorded in final-dependency-tests.txt and final-dependency-exit.json. This is the test set represented in the Repository Verification block below.
- scripts/validate.py passed, exit 0; the final handoff update is revalidated at closeout. git diff --check passed, exit 0.
- Earlier broad run: 291 tests, exit 1, 14 failures and one error. The reviewer identity check, fake workspace setup, continuation prompt and long TEMP-path fixture were corrected; the focused rerun above leaves only the OS blocker. Two initial broad attempts were interrupted (exit 1) after discovering recursive legacy repository copies caused by TEMP beneath runtime; task-created recursive temporary files were removed and TEMP moved to excluded __pycache__.

## Risks / Caveats

- Task remains blocked. Do not enable automatic builder execution from this handoff. The real successful token/label/process path, authenticated CLI run and isolated completion commands are unproven on this host.
- This is an uncommitted working-tree implementation at baseline 920528b5fdfa3e03965e95375481444b7457136e. Empty commit-bound verification fields below are intentional; no commit, push, network, user creation or policy change was performed.
- No session pickup operation was run. CLI tests invoked the scripts only with the builder guard (exit 3) or --help (exit 0), before assignment operations. No real assignment, lock or claim was claimed/released/modified. Canonical checkout, live state and deploy clones were not accessed; tests used only temporary stand-ins within this checkout.
- The v2 field known_exempt_failures identifies the nonzero OS test for structural validation; it does not waive the required adversarial proof. No clean overall test result is claimed.

## Recommended Next Action for Receiver

Review the diff, run the real adversarial fixture under the intended supervisor token, resolve any implementation or host-policy failures without weakening the boundary, verify the installed Grok policy/auth behavior, and migrate the legacy local route. Then rerun all required tests and prepare commit-bound evidence. Preserve the blocked status until the real proof passes.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-34-builder-isolation-contract
branch: agent/codex/m1-34-builder-isolation-contract
base_sha: 920528b5fdfa3e03965e95375481444b7457136e
implementation_sha:
tests_commit_sha:
final_head_sha: 920528b5fdfa3e03965e95375481444b7457136e
remote_head_sha:
git_status_clean: false
validator_commit_sha:
test_count: 94
test_exit_code: 1
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-34-BUILDER-ISOLATION-AND-CONTRACT__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-34-builder-isolation-contract
known_exempt_failures: ["tests.test_builder_isolation_contract.WindowsBoundaryTests.test_real_adversarial_builder_and_descendants"]
dependency_install: skipped
dependency_install_reason: Network and installs forbidden; existing signed runtime used.

## T-M1-34B

Replaced the failing account-resolving icacls /grant with stdlib ctypes Win32
DACL APIs. The fresh random SID remains unchanged. The SID trustee receives
GRANT_ACCESS with Modify rights (0x1301BF), merged into each existing DACL.
Directories receive object/container inheritance and existing children receive
explicit grants, including protected children. Win32 status codes raise
IsolationError; null DACLs and traversal errors also refuse launch. Allocated
SID/security-descriptor/ACL buffers are freed. Low labelling still uses icacls.
No changes to assignment/lock handling, T-M1-33 areas or execution enablement.

Added ACL unit tests for SID fields, rights, inheritance, child enumeration,
existing DACL merge, memory cleanup and read/merge/apply failures. Mocked tests
are not real write-denial proof. Claude must run the adversarial test with the
normal unrestricted supervisor token; this already-restricted sandbox cannot
create the fresh restricted token (WinError 87). Status remains blocked pending
that proof and the previously documented CLI checks.

Validation outputs: runtime/m1-34-validation/34b-tests.txt and
34b-test-exit.txt. Final results are recorded below after the run completes.

T-M1-34B final verification: 94 tests ran in 782.538 seconds; 93 passed,
one failed; TRUE test exit code 1. The only failure was
WindowsBoundaryTests.test_real_adversarial_builder_and_descendants, refused
at CreateRestrictedToken with WinError 87. New ACL unit tests passed. The run
included tests.test_builder_isolation_contract, tests.test_builder_watch,
tests.test_builder_supervisor_contract, the five-module guard pack,
tests.test_launch_resilience and tests.test_phase3_4_worktree_allocator.
The raw output and exit code are in 34b-tests.txt and 34b-test-exit.txt under
runtime/m1-34-validation. scripts/validate.py returned TRUE exit 0;
git diff --check returned exit 0. The final handoff update is revalidated
at closeout. No real boundary pass is claimed; Claude must exercise it under
the unrestricted supervisor token. No commits, network actions, session pickup,
assignment/claim/lock operations or access to the canonical/deploy clones was
performed for T-M1-34B.


## T-M1-34C

Supersedes the fresh SID/WRITE_RESTRICTED boundary and T-M1-34B ACL grant.
CreateRestrictedToken now uses DISABLE_MAX_PRIVILEGE only, zero restricting
SIDs, followed by Low integrity. Removed the unused ACL helper and ACE tests.
Reviewer evidence in TASK_34C.md establishes that WRITE_RESTRICTED causes
STATUS_DLL_INIT_FAILED on this host even without restricting SIDs.

Only the active clone/profile is Low-labelled. A named global Windows mutex
serializes builders. Before labelling, inspect every object in the configured
builder inventory for stale Low labels and refuse launch if any exist. Primary,
fallback and isolated acceptance launches preserve the allocator inventory root.
Root exit terminates remaining descendants and waits for the job to empty;
then restore Medium recursively, verify labels, and release the gate before
returning completion. Partial setup failures also restore labels. Restore
failures block completion/import; the import path independently checks labels.
Changed process_ownership only to route isolated termination through this label
cleanup. No assignment/lock/retry/dead-letter classifications were changed.

Revised the real temporary adversarial matrix: canonical .git write, task move,
inbox modification, claim delete/create, absolute-script and descendant writes,
other-builder write, HKCU and unique scheduled-task creation. Assert outside
files byte-identical, other builder untouched, no registry/task survivor (cleanup
registered even on failure), and workspace no longer Low. Setup fault tests
remain; lifecycle tests check job-empty -> Medium -> verify -> release ordering.

Docs now record the reviewer evidence table and residuals: LocalLow/other Low
paths writable, user-file reads possible (confidentiality out of scope), UIPI
blocks window messages to Medium. Per installed Grok README evidence supplied
in the contract, --sandbox is Landlock/Seatbelt only, not Windows. The installed
README was not accessed outside this clone. CLI deny/auth checks remain pending.

Real-token proof cannot be established in this already-restricted sandbox
(WinError 87); Claude must run the revised adversarial test under the normal
unrestricted supervisor token. Do not treat mocked lifecycle/setup checks as
write-denial proof. No enablement, network, commits or external-state operations.

T-M1-34C validation (TRUE process exits; runtime/m1-34-validation/34c-*):
- Initial required/core + guard pack + launch resilience + allocator: 94 tests,
  exit 1, two failures: real-token WinError 87 and Mock-based reused-PID fencing.
  The latter was fixed by dispatching only actual IsolatedProcess instances,
  rather than any object's truthy _mutex attribute. Ownership rerun: 11/11, exit 0.
- Final contract unit/lifecycle/setup checks + ownership: 25/25, exit 0
  (34c-final-unit-tests.txt, 34c-final-unit-exit.txt). This covers all final unit
  edits. Final core coverage is 97 checks when replacing superseded focused
  cases (an aggregate, not a single test run); its required real-boundary check
  remains failed, not waived. Repository Verification retains the initial
  core run's actual 94-test count and exit 1; reruns are itemized here.
- Real adversarial rerun after the global gate was free: 1 test, exit 1;
  CreateRestrictedToken refuses with WinError 87 before labelling/process launch
  (34c-real-token-rerun.txt, 34c-real-token-exit.txt). Claude must run this under
  the unrestricted supervisor token. No successful write-denial proof claimed.
- Earlier lifecycle attempt: exit 1 because the prior test process held the
  global gate; setup tests now use unique test mutexes. Earlier full-contract
  attempt: 15 tests, exit 1, only real proof blocked by that occupied gate.
  These intermediate failures remain recorded alongside the successful reruns.
- Affected-module run: 21 modules, 339 tests in 1186.305 seconds, all passed,
  TRUE exit 0 (34c-affected-tests.txt / 34c-affected-exit.txt). The module list
  is 34c-affected-modules.json; it includes every direct importer of files
  changed for C, supplementing the core required/guard-pack run.
- scripts/validate.py: exit 0. git diff --check: exit 0. The completed handoff
  is revalidated at closeout after recording the affected run.
