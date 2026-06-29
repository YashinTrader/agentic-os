# Handoff: T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX — Phase 3.7A.1 Main Executor Bypass Closure
**From:** composer
**To:** claude
**Date:** 2026-06-29T10:55:00Z
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did

- Added `dispatch/execution_route_policy.py` with `evaluate_execution_route()` fail-closed routing for canary-only adapters.
- Integrated route policy into `execution_gate.py` (before approval gates), `executor.py`, and `runtime_capture.py` result fields.
- Updated `codex_activation_gate.py` and `run_codex_canary.py` to identify `codex_canary` route before activation gates.
- Declared explicit route metadata on `codex-restricted`: `dedicated_runner_required: true`, `required_execution_route: codex_canary`.
- Added `validate_phase37a1_executor_bypass()` and nine H1 regression tests in `tests/test_phase3_7a_1_executor_bypass.py`.
- Added ADR-0042; qualified Phase 3.7A docs for M1 (generic path gap).

## What Remains

- Claude closeout review of Phase 3.7A.1 (H1 verification).
- ADR-0038–0041 Claude sign-offs remain pending until this fix is approved.
- Phase 3.7B blocked until Claude confirms H1 closed.

## Decisions Made

- Generic dispatch **always** rejects canary-only adapters, even with valid human approval and even if Phase 3.7B authorization exists.
- `supports_execution: true` is insufficient without matching execution route.
- Block reason: *Adapter requires its dedicated canary runner; generic dispatch execution is prohibited.*

## Open Questions

None blocking review.

## How to Verify My Work

```bash
cd C:/Users/gabot/agentic-os
git fetch origin
git checkout agent/composer/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX
python scripts/run_tests.py
python scripts/validate.py
python -m unittest tests.test_phase3_7a_1_executor_bypass -v
python scripts/run_codex_canary.py --json
python scripts/verify_repository_verification.py --handoff handoffs/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX__composer__to__claude.md
```

## H1 Main-Executor Bypass

| Scenario | Expected |
|----------|----------|
| Generic `--execute` + valid human approval + worktree | **Blocked** (route policy) |
| Generic `--execute` + Phase 3.7B authorization fixture | **Still blocked** |
| Dedicated `run_codex_canary.py` | Route allowed; later gates block (exit 3) |

## Execution Route Policy

- Module: `dispatch/execution_route_policy.py`
- Routes: `generic_dispatch`, `codex_canary`, `preview_only`
- Pure helper: no subprocess, secrets, approval consumption, or worktree mutation

## Generic Executor Integration

- Route check occurs before approval satisfaction, anti-replay claim, and subprocess.
- Blocked results include `execution_route_requested`, `execution_route_required`, `execution_route_allowed`, `route_block_reasons`.

## Codex Canary Integration

- `evaluate_execution_route(dedicated, ROUTE_CODEX_CANARY)` before fifteen activation gates.
- No weakening of Phase 3.7B prohibition; no live Codex subprocess added.

## Approval Consumption Ordering

Route block returns from `execute_dispatch()` before `try_claim_approval()`. `dispatch_blocked` event records `approval_consumed: false`.

## Regression Tests

`tests/test_phase3_7a_1_executor_bypass.py` — nine tests covering H1 scenarios A–H per task spec.

## Tests and Validator

- **460** tests, exit **0** at `tests_commit_sha`
- `validate.py` exit **0**

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX
base_sha: 2d29db6e41fd1d55f393f8a23f22803a4a75045f
implementation_sha: a8d945bf8b380474b0d33206520559668fa8ef6b
tests_commit_sha: a8d945bf8b380474b0d33206520559668fa8ef6b
artifact_sha: 3652cf02bcda7ab06f6a69c1eaece698a2737a9d
final_head_sha: de7b4bc1171f650222959c27441d07092cf61ac3
remote_head_sha: de7b4bc1171f650222959c27441d07092cf61ac3
git_status_clean: true
validator_commit_sha: a8d945bf8b380474b0d33206520559668fa8ef6b
test_count: 460
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX__composer__to__claude.md, docs/REVIEW_COMPOSER_PHASE_3_7A_1_SELF_REVIEW.md, runtime/unittest_last_run.txt, tasks/active/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX.yaml
working_copy_path: C:/Users/gabot/agentic-os

## Post-Test Diff

Only allowlisted closeout files after tested implementation commit.

## Safety Boundaries

- No live Codex prompt subprocess
- No human approval record created or consumed
- No Phase 3.7B authorization committed
- `local-python-exec-test` remains generic-executable
- Autonomy Level 1

## Risks / Caveats

- Route metadata must stay synchronized between registry YAML and dedicated adapter YAML
- Phase 3.7B still required for live canary inside dedicated runner only

## Recommended Next Action for Receiver

Claude closeout review of Phase 3.7A.1. If APPROVE, flip ADR-0038–0041 sign-offs; then Phase 3.7B may be opened under existing two-person gate. Do not run Codex in this milestone.