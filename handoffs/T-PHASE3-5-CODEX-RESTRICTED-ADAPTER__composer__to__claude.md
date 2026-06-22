# Handoff: T-PHASE3-5-CODEX-RESTRICTED-ADAPTER — Phase 3.5 Codex Restricted Adapter Candidate
**From:** composer
**To:** claude
**Date:** 2026-06-22T18:35:00Z
**Task Status After Handoff:** review
**Handoff Protocol:** v2

## What I Did

- Added `codex-restricted` adapter candidate (`agents/codex_restricted_adapter.yaml` + registry entry).
- Implemented command builder (`dispatch/codex_adapter.py`), context bundle, environment boundary, result parser.
- Added read-only CLI discovery (`scripts/inspect_codex_cli.py`), preview (`preview_codex_dispatch.py`), canary refusal script (`run_codex_canary.py`).
- Extended validator with Phase 3.5 adapter boundary rules.
- Created ADR-0029 through ADR-0033; clerical Claude sign-offs on ADR-0025–0028.
- Added 21 tests across seven `test_phase3_5_*.py` modules (387 total suite).
- Updated post-test allowlist for Phase 3.5 closeout verification.

## What Remains

- Claude final review of Phase 3.5.
- Separate clerical activation task to flip `codex-restricted` `supports_execution: true` (not in this milestone).
- Live Codex canary after activation (per `docs/PHASE_3_5_CODEX_CANARY_PLAN.md`).

## Decisions Made

- Separate adapter identity `codex-restricted`; did not promote `codex-cli-preview`.
- Codex CLI `exec` with `workspace-write` sandbox; danger bypass flags forbidden.
- Two-stage activation per ADR-0032.
- Context bundle under `runtime/dispatch/runs/<run_id>/codex_context/`.
- Canary script refuses until post-activation operator flags.

## Open Questions

- Whether `OPENAI_API_KEY` alone is sufficient for Codex auth in all operator environments (documented in ADR-0030).

## How to Verify My Work

```bash
cd C:/Users/gabot/agentic-os
git fetch origin
git checkout agent/composer/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER
python scripts/run_tests.py
python scripts/validate.py
python scripts/verify_repository_verification.py --handoff handoffs/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER__composer__to__claude.md
git diff 4d7da038536d58e03a455ae6e4173af3fad74d0a..HEAD --name-only
```

## Codex CLI Discovery

- **Version:** codex-cli 0.136.0
- **Path:** `%AppData%/npm/codex` (Windows)
- **Non-interactive:** `codex exec`
- **Flags used:** `-C`, `-s workspace-write`, `--json`, `-o`
- **Forbidden:** `--dangerously-bypass-approvals-and-sandbox`, `--dangerously-bypass-hook-trust`

## Adapter Contract

- `id: codex-restricted`, `promotion_state: restricted_candidate`
- `supports_execution: false`, `approval_level: human`
- `worktree_required`, `network_required`, `secrets_required: true`

## Command Safety

- Pure argv builder; no `shell=True`; bounded prompt/context
- Fixed subcommand `exec`; forbidden danger flags blocked at builder and preview gate

## Environment Boundary

- `dispatch/agent_environment.py` allowlist/denylist; previews list variable names only
- HMAC keys and unrelated cloud tokens denied

## Worktree Enforcement

- `evaluate_allocation_for_execution` integrated in command builder
- No auto-allocation, merge, push, or worktree deletion

## Approval and Anti-Replay

- Human approval required; Phase 3.4 HMAC + replay gates apply when execution is activated
- Executor blocks `supports_execution: false` today — no live Codex subprocess reachable

## Context Bundle

- Atomic writes; size limits; manifest hash excludes manifest.json from content hash
- No secrets in bundle files

## Result Contract

- `dispatch/agent_result_parser.py` — exit 0 alone insufficient for `completed_verified`
- Requires handoff, verification results, and diff evidence

## Canary Plan

- Documented in `docs/PHASE_3_5_CODEX_CANARY_PLAN.md`
- `run_codex_canary.py` exits 3 (refused) without activation

## Activation Boundary

- **Not activated.** `codex-restricted` remains `supports_execution: false`.
- Only `local-python-exec-test` is executable.

## Tests and Validator

- **387** tests, exit **0** at `implementation_sha` `4d7da03`.
- Validator exit **0** at implementation and final HEAD.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER
base_sha: f39188ab882af99920292adbed136effd1f10ffb
implementation_sha: 4d7da038536d58e03a455ae6e4173af3fad74d0a
tests_commit_sha: 4d7da038536d58e03a455ae6e4173af3fad74d0a
final_head_sha: f583c774748d205ad56ae6f0f34ad6860fa18f20
remote_head_sha: f583c774748d205ad56ae6f0f34ad6860fa18f20
git_status_clean: false
validator_commit_sha: 4d7da038536d58e03a455ae6e4173af3fad74d0a
test_count: 387
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: verification-only-allowlist-phase35
post_test_files: runtime/unittest_last_run.txt, handoffs/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER__composer__to__claude.md, docs/REVIEW_COMPOSER_PHASE_3_5_SELF_REVIEW.md, tasks/active/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER.yaml
working_copy_path: C:/Users/gabot/agentic-os

## Post-Test Diff

Only explicit verification artifacts after `tests_commit_sha`. No `decisions/**`, code, tests, or scripts changes.

## Safety Boundaries

- `codex-restricted` `supports_execution: false`
- No live Codex in tests; no network/API calls
- Autonomy Level 1 unchanged
- No scheduler, MCP execution, or dashboard execute controls

## Risks / Caveats

- Context instructions path is in repo `runtime/`, not worktree; Codex `-C` scopes writes to worktree.
- Activation requires separate milestone after Claude approval.

## Recommended Next Action for Receiver

Claude final review of Phase 3.5. If approved, open clerical activation task only — do not activate in this review pass.