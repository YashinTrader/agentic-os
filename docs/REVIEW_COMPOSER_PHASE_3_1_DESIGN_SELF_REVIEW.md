# Composer Self-Review — Phase 3.1 Design (T-PHASE3-1-DESIGN)

**Reviewer:** composer (internal builder/reviewer loop)  
**Date:** 2026-06-11  
**Branch:** `agent/composer/T-PHASE3-1-DESIGN`

## Verdict

**APPROVE WITH CHANGES** (fixes applied before handoff)

## Scope check

| Expected | Actual |
|----------|--------|
| Design docs only | ✅ Six docs + review packet |
| Contract modules (no execution) | ✅ executor, approval, freshness |
| ADR-0014/0015/0016 | ✅ Created, INDEX updated |
| Tests for contracts | ✅ 26 new tests across 3 files |
| No executor runtime | ✅ No subprocess imports |
| No dashboard buttons | ✅ No dashboard changes |
| Optional schemas | ✅ Two JSON schemas added |

No scope creep into Phase 3.2 implementation detected.

## Safety check

| Check | Result |
|-------|--------|
| `subprocess` in new dispatch modules | ✅ Only docstring mention in executor_contract |
| `os.system` / `os.popen` | ✅ Absent |
| Execution events in ALLOWED_EVENT_TYPES | ✅ PHASE_3_2 events reserved only |
| Task mutation by dispatch | ✅ Not introduced |
| Auto-merge / push | ✅ Not introduced |

## Test check

- `python scripts/run_tests.py` → **214 OK**, exit 0
- `python scripts/validate.py` → **passed** (historical v1 log warnings only)
- KEY=VALUE, freshness, approval expiry, worktree block, CLI gate covered

## Protocol check

- `ALLOWED_EVENT_TYPES` unchanged for Phase 3.0 preview events
- `PHASE_3_2_EXECUTION_EVENT_TYPES` documented in `event_types.py`
- Preview module extended with KEY=VALUE helper (preview-only validation)

## Phase 3.2 blockers

1. Explicit implementation task after Claude ADR review
2. Approval recording workflow (human/reviewer UI or file-based operator step)
3. Git worktree allocator and pre-execution snapshot
4. Subprocess executor with timeout and runtime log writers
5. Event emitters for reserved execution events
6. Network/MCP policy enforcement beyond contract flags

## Required fixes found by self-review

| ID | Finding | Severity |
|----|---------|----------|
| F1 | `is_preview_stale` did not prefer live `current_task` for hash | Medium |
| F2 | Duplicate shlex warnings if KEY=VALUE validator re-parsed tokens | Low |

## Fixes applied

- **F1:** Updated `preview_hash_payload` to prefer live `task`/`adapter` context for
  `task_id`, `adapter_id`, and `risk_level` when computing staleness hashes.
- **F2:** `validate_key_value_forbidden_args` accepts pre-parsed `tokens` to avoid
  duplicate warnings from `validate_command_allowlist`.

## Remaining risks

1. **KEY=VALUE edge cases** — Combined tokens like `--foo=bar=baz` use first `=` split only;
   exotic CLI syntax may need adapter-specific rules in Phase 3.2.
2. **CLI inventory absent** — Missing `cli_inventory.yaml` blocks execution at validation;
   preview path does not yet surface this (Phase 3.2 integration).
3. **`codex-cli-preview`** — `writes_files: true` with `repo_root` policy requires
   worktree at execution time; preview still shows `repo_root` cwd (documented in review packet).
4. **Approval `valid` flag** — `approval_level: none` records are intentionally awkward;
   execution path should not load approval records for preview-only mode.

## Recommendation

Safe for Claude final review. Phase 3.2 implementation must remain gated on ADR acceptance
and a separate execute-path task.