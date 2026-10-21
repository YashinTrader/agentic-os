# Handoff: T-M1-02D-PAID-QUOTA-PROBE

**From:** codex
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** awaiting_review
**Handoff Protocol:** v2

## What I Did

- Added `orchestrator/quota_probe.py` and enabled `agents/quota_probe.yaml` with
  a 3600-second provider interval and configurable Codex model (`gpt-5.4-mini`).
  Intervals below 3600 require literal `owner_override: true`. An absent config
  disables paid probes.
- Provider probes run only for current quota-blocked builders below the retry
  cap, excluding already-dispatched and escalated runs. One probe serves all
  blocked runs for that provider. Free authentication probes retain their
  existing behavior.
- Implemented the requested Codex, Grok, and Claude commands, resolved executable,
  `shell=False`, closed stdin, empty temporary cwd, and 120-second communication
  deadline. Launch uses `owned_popen`; cleanup calls `terminate_owned`, including
  on timeout, then bounded wait and pipe cleanup. Windows uses the existing
  kill-on-close Job Object path.
- Codex requires structured agent-message `ok` or `turn.completed`; usage-limit
  text or `turn.failed` defeats success. Grok requires a non-error JSON result
  without quota/payment/balance text. Claude requires `ok` with successful exit.
- Persisted hourly reservations in
  `runtime/dispatch/paid_quota_probes.json`, under the existing OS guard. The
  reservation is written before launch and survives a crash or new process.
  Corrupt rate-limit state fails closed. The guard remains held through each
  bounded probe and evidence write; competing supervisors skip that tick.
- Paid timestamps retain subsecond precision. Monotonic elapsed time accounts
  for earlier probes in the same tick, so a slow first provider cannot shorten
  the next provider's hourly window.
- Appended durable start and terminal records to
  `runtime/dispatch/paid_quota_probes.jsonl`, including provider, started_at,
  duration in seconds, outcome, exit_code, and classification. Starts preserve
  evidence for interrupted probes. Raw CLI output is not stored.
- Successful recovery persists `next_eligible_at` for every affected blocked
  run before dispatching one retry. Later ticks can dispatch remaining runs
  without another paid probe. Existing retry caps, preserved worktree/lock,
  and single-relaunch scheduling remain in force.
- Supervisor status now exposes `quota_probes.<provider>.last_paid_probe_at`
  and `quota_probes.<provider>.paid_probes_24h` (counting starts).
- Updated `docs/PHYSICAL_AGENT_LAUNCHER.md` and registered this exact handoff
  path in `POST_TEST_ALLOWLIST_EXACT` before the final focused tests.

## Verification Results

- Initial RED: `python -m unittest tests.test_quota_probe` failed because the
  referenced quota probe module did not exist.
- Final focused modules: `tests.test_builder_condition_retry`,
  `tests.test_quota_probe`, `tests.test_process_ownership_fencing`, and
  `tests.test_physical_agent_launcher`: **54 tests, 31.398 seconds, exit 0**.
- New quota probe tests: **17**, covering no blocked/auth-only runs, disabled
  configuration, corrupt ledger, fresh Python process persistence, lock
  contention, failure throttling, independent provider windows, append-only
  evidence, 24-hour counters, shared recovery, retry cap, invalid interval,
  owner override, argv restrictions, structured output, usage limits, timeout
  ownership cleanup, launch errors, and supervisor status.
- Standard-library `trace` statement coverage for `orchestrator/quota_probe.py`:
  **165/186 executable lines, 88.7%**, measured during the final focused run
  including module imports. No coverage dependency was installed.
- `python scripts/validate.py`: exit 0 before this handoff; rerun after writing
  this handoff. Existing deprecated event-field warnings only.
- `git diff --check`: exit 0. Only Git's LF/CRLF notices.
- All provider CLIs were mocked. Existing ownership tests launch local Python
  children to verify real tree termination; the persistence test starts a fresh
  Python process with the probe mocked. No real paid probe, credential operation,
  network access, pickup script, or full suite was run.

## How to Verify My Work

Normal environments can run:

```powershell
python -m unittest tests.test_builder_condition_retry tests.test_quota_probe tests.test_process_ownership_fencing tests.test_physical_agent_launcher
python scripts/validate.py
```

This Windows sandbox rejects access to directories created with Python's
temporary-directory mode 0700, including inside the clone. The successful run
used an in-process test-runner-only `os.mkdir` wrapper to retain inherited ACLs,
with TEMP and TMP inside the clone. Production code was not patched for this.
The equivalent focused test runner is:

```powershell
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
python -c "import os, unittest; original=os.mkdir; os.mkdir=lambda path, mode=0o777, **kw: original(path, 0o777, **kw); unittest.main(module=None, argv=['unittest','tests.test_builder_condition_retry','tests.test_quota_probe','tests.test_process_ownership_fencing','tests.test_physical_agent_launcher'])"
```

For coverage, the final run wrapped loading and running those four modules with
`trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix]).runfunc(...)`.
Coverage is the intersection of executed module lines with
`trace._find_executable_linenos(module_path)`.

## Decisions Made

- Use conservative pre-launch reservations: a failed or interrupted probe still
  consumes its hourly window. Count starts for status and record terminal results
  separately, preserving evidence after interruption.
- Keep authentication and quota probes separate. Persist shared eligibility on
  run records rather than reusing a cached success for future blocked attempts.
- Keep network access disabled during implementation and verification.

## Open Questions

- Receiver should confirm the desired cheapest supported Codex model before
  production use; no live model or pricing lookup was permitted.

## What Remains

Commit and refresh git-backed verification in a write-enabled checkout.

## Risks / Caveats

- **Implementation is uncommitted.** `git add` and the TDD checkpoint commit
  were attempted, but the sandbox denied creation of `.git/index.lock`.
  No approval escalation is available. The implementation and tests are local
  working-tree files ready for review; no push or merge was attempted.
- The SHA fields below are checkout/base anchors required by the v2 format,
  **not an attestation that the implementation exists in that commit**. Tests
  and validation ran against the modified working tree. Receiver must commit,
  rerun focused verification, and replace the anchors before using a git-backed
  closeout gate. The remote branch was not updated or queried over the network.
- `runtime/unittest_last_run.txt` was not regenerated; it is not evidence of
  this focused run. No full-suite claim is made.
- `pip audit` was not run: dependency auditing requires network access, forbidden
  by this task. Dependencies were not changed.
- Configured Codex model availability/pricing was not checked against a live
  service. The model is configurable; the receiver should confirm the desired
  cheapest supported model before enabling this configuration in production.
- Existing untracked `TASK_INSTRUCTIONS.md`, `codex_stdout.jsonl`, and
  `codex_stderr.log` were left untouched. Early temporary-directory attempts
  left inaccessible empty scratch directories in the default OS temp location
  and under `.tmp`. Subsequent successful test runs used clone-local temp only;
  no permission changes or outside-clone cleanup was attempted.

## Recommended Next Action for Receiver

Review the local diff, add the new module/config/tests/handoff, commit in a
write-enabled checkout, rerun the focused checks, and refresh verification
anchors. Keep any real paid execution outside test verification.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-02d-quotaprobe
branch: agent/codex/T-M1-02D-PAID-QUOTA-PROBE
base_sha: 211c9b9488491d4e1d23ed411c55d4f84ad8be62
implementation_sha: 211c9b9488491d4e1d23ed411c55d4f84ad8be62
tests_commit_sha: 211c9b9488491d4e1d23ed411c55d4f84ad8be62
final_head_sha: 211c9b9488491d4e1d23ed411c55d4f84ad8be62
remote_head_sha: 211c9b9488491d4e1d23ed411c55d4f84ad8be62
git_status_clean: false
validator_commit_sha: 211c9b9488491d4e1d23ed411c55d4f84ad8be62
test_count: 54
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-M1-02D-PAID-QUOTA-PROBE__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-02d-quotaprobe

## T-M1-02E correction — 2026-10-21

- Changed the configured Codex model to `gpt-6.1-sol`, with the requested
  host-verification comment (ChatGPT-account plan; `gpt-5.4-mini` rejected).
  This supersedes the original model-selection caveats above; no live probe
  was performed during this correction.
- Unsupported model, invalid request, unknown model, and account-plan mismatch
  output now classify as `probe_misconfigured` before quota matching. Evidence
  includes that classification and a safe configuration reason, without raw output.
- Persisted the latest classification and alert reason in the existing ledger.
  Supervisor status exposes `quota_probe_alerts.<provider>` with classification
  and reason. Later terminal results clear stale configuration alerts.
- Misconfiguration never returns quota recovery or `blocked_quota`; it leaves
  the existing blocked run unchanged. The pre-launch reservation still prevents
  another paid probe before the configured normal 3600-second interval.
- Focused verification: `tests.test_quota_probe` and
  `tests.test_builder_condition_retry`: **30 tests, 11.530 seconds, OK**.
  Used the previously documented clone-local TEMP/TMP and test-only mkdir ACL
  wrapper. New tests cover model default, misconfiguration precedence/evidence,
  supervisor alert, hourly throttle, and quota failure clearing the alert.
- `python scripts/validate.py`: **exit 0**, existing event-field warnings only.
  `git diff --check`: **exit 0**. Prior accepted implementation preserved.
- Left uncommitted because this sandbox grants only read access to `.git`.
  No pickup, full suite, paid probe, push, merge, or outside-clone write ran.
