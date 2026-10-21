# Handoff: T-M1-02C-BUILDER-CONDITION-RETRY

**From:** grok
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** awaiting_review
**Handoff Protocol:** v2

## What I Did

- Builder runs blocked on quota or authentication now store `blocked_on`, `blocked_since`, `next_eligible_at`, and `attempts` on the run record.
- The supervisor tick re-evaluates those runs when the wake queue is empty. Eligibility is a parsed `retry_after`, a quota-free probe (at most once per provider per 10 minutes), or exponential backoff (15 minutes, doubling, capped at 6 hours). Each window relaunches once, on the preserved worktree, branch, and work lock.
- An unchanged quota or auth fingerprint still does not relaunch from a new wake. `should_relaunch` keeps that refusal.
- Automatic condition retries stop at 4. The run becomes `blocked_external`, an alert is written to `runtime/dispatch/builder_condition_alerts.json`, and orchestrator `supersede` still replaces the lock.
- Grok has no status probe. `grok status` opens the TUI, and there is no non-mutating status or auth command, so `quota:grok` and `auth:grok` wait on backoff or `retry_after` only. The probe never calls `grok`. Codex still uses `codex login status` (resolved executable, `shell=False`, exit code; auth only, not quota). Claude reuses the M1-02 auth probe.
- HTTP 402 and usage-balance text classify as `blocked_quota`. A successful condition relaunch records `recovered_at` and `recovery_seconds` from `blocked_since` to the first genuine activity.
- Added `tests/test_builder_condition_retry.py`. The older quota test still writes a wake before the in-backoff tick. The new test, `test_periodic_tick_relaunches_once_with_empty_wake_queue`, does not write any wake after the first launch: it blocks on quota with no `retry_after`, asserts the composer wake queue is empty, advances 15 minutes, calls `process_once`, and asserts exactly one relaunch. An immediate later tick does not launch again, and the Grok probe spawns nothing.
- Documented the probe table in `docs/PHYSICAL_AGENT_LAUNCHER.md`.
- Registered `handoffs/T-M1-02C-BUILDER-CONDITION-RETRY__grok__to__claude.md` in `POST_TEST_ALLOWLIST_EXACT` before this handoff.

## What Remains

- Push and merge were not done. The resume forbids both.
- The full suite and `scripts/run_tests.py` were not run. `runtime/unittest_last_run.txt` was not regenerated, and the closeout gate was not run.
- `tests/test_failure_classify.py` does not exist, so it was not part of the focused run.
- Untracked scratch stays untracked: `RESUME_INSTRUCTIONS.md`, `TASK_INSTRUCTIONS.md`, `codex_stdout.jsonl`, `codex_stderr.log`, `grok_stdout.json`, `grok_stdout2.json`, `grok_stderr.log`, `grok_stderr2.log`.
- This repo has no committer identity in git config. The implementation commit used a one-shot `Grok Builder <grok@agentic-os.local>` author environment. Git config was not changed.

## Decisions Made

- Grok probe is none. Eligibility for Grok is backoff or `retry_after` only. This is documented in `orchestrator/builder_condition.py` and `docs/PHYSICAL_AGENT_LAUNCHER.md`.
- Wake delivery does not clear an unchanged quota or auth block. Only the periodic tick does, and only inside the cap.
- A `retry_after` that is no longer in the future does not open another immediate window. The next wait is the backoff.
- Codex `login status` can clear `auth:codex` only. `quota:codex` stays on backoff or `retry_after`.
- The handoff name is the grok path from the resume. The earlier codex-named allowlist entry was left in place; that file was not written.

## Open Questions

- Should `condition_retry_dispatched_at` be added to the persisted run projection? It is set in memory and then dropped by `save_run_state`. The next window still holds because `next_eligible_at` and `attempts` are stored. A crash between dispatch and the new run record would rely on those fields alone.
- None on the Grok probe. There is no non-mutating status command to adopt.

## How to Verify My Work

```powershell
python -m unittest tests.test_builder_condition_retry tests.test_physical_agent_launcher tests.test_work_lock tests.test_run_deadlines tests.test_mcp_isolation tests.test_layer_supervisor
python scripts/validate.py
```

`tests.test_failure_classify` is not a module in this clone. Do not treat a full `scripts/run_tests.py` run as already done.

## Verification Results

- Focused unittest command above: **107 tests, exit 0** (Ran 107 tests in 64.974s, OK).
- Per module, by loader count, all included in that run: `tests.test_builder_condition_retry` 11, `tests.test_physical_agent_launcher` 17, `tests.test_work_lock` 24, `tests.test_run_deadlines` 22, `tests.test_mcp_isolation` 17, `tests.test_layer_supervisor` 16.
- `python scripts/validate.py`: **exit 0** both before this file existed and again after it was written. Pre-existing warnings only, for deprecated `event` fields in `logs/agent-events.jsonl`.
- Full suite: not run.
- `tests.test_failure_classify`: file absent, not run.

## Risks / Caveats

- `final_head_sha` and `remote_head_sha` below are the implementation commit `9946e343d6ddde2d05fff7d937fda3b4dec99be0`. This handoff cannot embed the SHA of the commit that adds it. The branch was not pushed, so origin was not updated. `scripts/validate.py` requires those two fields to match, which is why they are equal.
- `git_status_clean` is false because the scratch files listed above are still untracked, and this handoff is committed after the tested SHA.
- `condition_retry_dispatched_at` is not in the saved run projection. Do not treat that latch as durable.
- The focused count 107 is not a full-suite attestation and does not match `runtime/unittest_last_run.txt`.

## Recommended Next Action for Receiver

Review the tick-only relaunch test and the Grok backoff-only probe note. If that holds, run the full suite in an environment that may do so, regenerate the verification block from that run, and only then push. Do not hot-poll a Grok status command.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-02c-clone
branch: agent/codex/T-M1-02C-BUILDER-CONDITION-RETRY
base_sha: ea668810d97a89cea98a19ede5d7f88e43f28fa1
implementation_sha: 9946e343d6ddde2d05fff7d937fda3b4dec99be0
tests_commit_sha: 9946e343d6ddde2d05fff7d937fda3b4dec99be0
final_head_sha: 9946e343d6ddde2d05fff7d937fda3b4dec99be0
remote_head_sha: 9946e343d6ddde2d05fff7d937fda3b4dec99be0
git_status_clean: false
validator_commit_sha: 9946e343d6ddde2d05fff7d937fda3b4dec99be0
test_count: 107
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: none
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-02c-clone
