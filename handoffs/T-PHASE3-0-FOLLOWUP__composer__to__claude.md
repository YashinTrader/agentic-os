# Handoff: T-PHASE3-0-FOLLOWUP — Phase 3.0.1 cleanup before Phase 3.1 design
**From:** composer
**To:** claude
**Date:** 2026-06-08T12:00:00Z
**Task Status After Handoff:** review

## What I Did
- **M1:** Added `.gitignore` entries for `runtime/dispatch/**` (with `.gitkeep` exceptions) and `logs/dispatch-*.jsonl`.
- **M2:** Replaced substring `forbidden_args` checks with token-level matching via `command_tokens()` + `shlex.split`; added regression tests for false positives and exact-token matches.
- **M3:** Added `resolve_approval_gate()` / `blocked_approval_gate()` — missing or inactive adapter now returns `approval_level: blocked` and `approval_status: blocked` with explicit reasons.
- **M4:** Created `decisions/ADR-0013-adapter-registry-schema.md` and updated `decisions/INDEX.md`.
- **L1:** Documented dispatch run log stream split in `docs/AGENT_PROTOCOL.md` §6.0.1.
- **L2:** Fixed double `dispatch-` log prefix — `logs_path` is now `logs/{run_id}.jsonl`.
- **L3:** Removed dead `approval_status: "pending"` assignment in `merge_approval_gate`.
- **L4:** Documented `dispatch_allowed` semantics, token-level forbidden args, and blocked-adapter behavior in `docs/PHASE_3_DESIGN_SPEC.md`.
- **L5:** Flipped claude sign-off boxes on ADR-0010/0011/0012; added Phase 3.0 consequences note to ADR-0012.
- Extended `tests/test_dispatch_preview.py` with 8 new tests (token allowlist, blocked gates, gitignore, ADR-0013, log path).

## What Remains
- Claude re-review of M2/M3 fixes and ADR-0013.
- Phase 3.1 **design ADR only** (execute path, approval recording, subprocess sandbox) — no implementation.
- CLI availability cross-check against `runtime/registry/cli_inventory.yaml` (Phase 3.1 design item I2).
- Preview freshness window for executor (Phase 3.1 design item I1).

## Decisions Made
- Token-level `forbidden_args` implemented in Phase 3.0 (preview-only) per user mission override of task yaml deferral.
- `approval_level: blocked` forced whenever adapter is missing or inactive (M3 option a).
- Log filename uses `logs/{run_id}.jsonl` because `run_id` already includes `dispatch-` prefix.
- ADR-0013 approval level: reviewer (not human).

## Open Questions
- Should `runtime/dispatch/latest_preview.json` be gitignored explicitly or is `runtime/dispatch/**` sufficient? (Currently covered by `**`.)
- Phase 3.1 design ADR number — ADR-0014 for execute path?

## How to Verify My Work
```bash
python scripts/run_tests.py
python scripts/validate.py
python scripts/preview_dispatch.py --json --no-write --no-log
python scripts/preview_dispatch.py --adapter blocked-mcp-preview --json --no-write --no-log
# Expect approval_gate.approval_level == blocked, approval_status == blocked
grep -E "runtime/dispatch|logs/dispatch" .gitignore
test -f decisions/ADR-0013-adapter-registry-schema.md
```

Review:
- `docs/REVIEW_CLAUDE_PHASE_3_0.md` (original findings M1–M4)
- `decisions/ADR-0013-adapter-registry-schema.md`

## Risks / Caveats
- Token-level check does not parse `arg=value` combined tokens; forbidden `--execute` in `--execute=true` may not match until Phase 3.1 hardening.
- `command_tokens` falls back to whitespace split on shlex errors — safe but may miss edge-case quoting.
- No subprocess execution added; preview module still has no `import subprocess`.
- Phase 3.1 executor must consume both `dispatch_allowed` and `approval_gate.approval_status`.

## Recommended Next Action for Receiver
1. Re-review M1–M4 fixes against `docs/REVIEW_CLAUDE_PHASE_3_0.md`.
2. If approved, merge `agent/composer/T-PHASE3-0-FOLLOWUP` into Phase 3.0 branch / main.
3. Open **T-PHASE3-1-DESIGN** — draft Phase 3.1 execute-path ADR only (no `execute_dispatch.py` implementation yet).