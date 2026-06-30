# Handoff: T-PHASE3-6-CODEX-ACTIVATION-READINESS — Phase 3.6 Codex Activation Readiness
**From:** composer
**To:** claude
**Date:** 2026-06-28T15:05:00Z
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did

- Fixed MA1: `append_codex_prompt()` preserves `-o` output path (no `argv[-1]` overwrite).
- Added activation manifest builder/validator (`dispatch/codex_activation.py`).
- Added documentation-only canary contract (`dispatch/codex_canary_contract.py`).
- Added CLI compatibility evaluator (`dispatch/codex_cli_compatibility.py`).
- Added twelve-layer canary gates (`dispatch/codex_canary_gates.py`).
- Updated `run_codex_canary.py` to refuse before any Codex subprocess.
- Added `validate_codex_activation.py` (outputs `READY_FOR_REVIEW` only).
- Added schemas, Phase 3.6 docs, ADR-0034–0037, ADR-0029–0033 Claude sign-offs.
- Added 39 Phase 3.6 tests (426 total suite).
- Updated post-test allowlist for Phase 3.6 closeout.

## What Remains

- Claude final review of Phase 3.6.
- Separate human-approved activation task to flip `supports_execution: true`.
- First live documentation-only canary after activation.

## Decisions Made

- Prompt is trailing positional after `-o` path per Codex CLI help.
- Activation manifests capped at pre-active status in this milestone.
- Canary contract hash binds documentation-only single-file scope.
- Emergency disable via `runtime/dispatch/codex_emergency_disable.json`.

## Open Questions

- Windows `codex.CMD` read-only inspect may return empty `exec --help`; operator must verify CLI help before live activation.

## How to Verify My Work

```bash
cd C:/Users/gabot/agentic-os
git fetch origin
git checkout agent/composer/T-PHASE3-6-CODEX-ACTIVATION-READINESS
python scripts/run_tests.py
python scripts/validate.py
python scripts/validate_codex_activation.py
python scripts/verify_repository_verification.py --handoff handoffs/T-PHASE3-6-CODEX-ACTIVATION-READINESS__composer__to__claude.md
```

## MA1 Command Fix

- `build_codex_exec_options()` ends at output path; `append_codex_prompt()` adds prompt last.
- `validate_codex_argv_contract()` regression-tested in `test_phase3_6_codex_command.py`.

## CLI Compatibility

- Read-only: `codex --version`, `--help`, `exec --help` via `inspect_codex_cli.py`.
- Fixture-based tests; repository validation does not require Codex installed.

## Activation Manifest

- Schema: `schemas/codex_activation_manifest.schema.json`
- Status in this branch: `reviewer_approved` / `awaiting_human_approval` only

## Human Approval Boundary

- Checklist only: `docs/PHASE_3_6_HUMAN_APPROVAL_CHECKLIST.md`
- No approval consumed in Phase 3.6

## Canary Contract

- Exactly one `docs/codex-canary-<run-id>.md`; prepared not executed

## Canary Refusal

- `run_codex_canary.py` exit **3**; twelve gates; no Codex subprocess

## Rollback and Emergency Disable

- `docs/PHASE_3_6_CODEX_ROLLBACK.md`

## Tests and Validator

- **426** tests, exit **0** at `implementation_sha`
- `validate.py` exit **0**

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-6-CODEX-ACTIVATION-READINESS
base_sha: 2af82a9e7e812e05059b69653583d1c78dfa43b1
implementation_sha: 91a3e6d775991a8a2632bf6fdb6f51bb5d5ff728
tests_commit_sha: 91a3e6d775991a8a2632bf6fdb6f51bb5d5ff728
final_head_sha: 1ec57fa43af93c811fb276c3745cb319bc4379dc
remote_head_sha: 1ec57fa43af93c811fb276c3745cb319bc4379dc
git_status_clean: true
validator_commit_sha: 91a3e6d775991a8a2632bf6fdb6f51bb5d5ff728
test_count: 426
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-PHASE3-6-CODEX-ACTIVATION-READINESS__composer__to__claude.md, docs/REVIEW_COMPOSER_PHASE_3_6_SELF_REVIEW.md, runtime/unittest_last_run.txt
working_copy_path: C:/Users/gabot/agentic-os

## Post-Test Diff

Only allowlisted closeout files after tested implementation commit.

## Safety Boundaries

- `codex-restricted.supports_execution: false`
- Only `local-python-exec-test` executable
- No live Codex prompt subprocess; no canary run

## Risks / Caveats

- CLI inspect on Windows may need operator re-run before activation

## Recommended Next Action for Receiver

Claude final review of Phase 3.6. If APPROVE, schedule separate human-approved activation + first documentation-only canary.