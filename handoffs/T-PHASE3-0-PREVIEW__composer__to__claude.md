# Handoff: T-PHASE3-0-PREVIEW — Phase 3.0 dispatch dry-run preview
**From:** composer
**To:** claude
**Date:** 2026-06-08T00:00:00Z
**Task Status After Handoff:** review

## What I Did
- Added `agents/adapter_registry.yaml` with five adapter entries (four active CLI previews, one disabled MCP placeholder).
- Implemented `dispatch/preview.py` — plan/task load, adapter selection, command template expansion, allowlist/forbidden-args enforcement, risk-gate merge, preview persistence under `runtime/dispatch/`.
- Added `scripts/preview_dispatch.py` CLI (`--adapter`, `--plan`, `--task`, `--json`, `--no-write`, `--no-log`).
- Added read-only **Dispatch Preview** dashboard tab (`/?tab=dispatch`) — no execute controls.
- Extended `scripts/validate.py` with `validate_adapter_registry()`.
- Added `dispatch_preview_created` and `dispatch_blocked` to `protocol/event_types.py`.
- Added `tests/test_dispatch_preview.py` covering registry, allowlist, risk gate, output shape, and no-subprocess guarantee.
- Documented execution blockers in `docs/PHASE_3_0_BLOCKERS.md`.

## What Remains
- Claude review of preview schema, approval merge logic, and ADR-0012 alignment.
- Phase 3.1 `execute_dispatch.py` (explicit `--execute` only) — not started.
- Human approval recording UI/workflow for high-risk previews.
- CLI availability checks against `runtime/registry/cli_inventory.yaml` at preview time (optional hardening).

## Decisions Made
- Preview module has no `subprocess` import — execution must live in a separate module in Phase 3.1+.
- MCP adapter registered as `disabled` with `supports_dry_run: false` to document future shape without enabling invocation.
- Exit code 2 from `preview_dispatch.py` when `dispatch_allowed` is false (blocked preview).
- Execution events (`dispatch_started`, etc.) remain in `RESERVED_EVENT_TYPES` until Phase 3.1+.

## Open Questions
- Should preview require a fresh orchestration plan (< N hours) before Phase 3.1 execute?
- Should `required_clis` missing from inventory downgrade to `dispatch_allowed: false` with warning?
- ADR-0013 for adapter registry schema — create now or with Phase 3.1?

## How to Verify My Work
```bash
python scripts/run_tests.py
python scripts/validate.py
python scripts/orchestrate_task.py --task tasks/active/T-PHASE3-0-PREVIEW.yaml
python scripts/preview_dispatch.py --json
python scripts/preview_dispatch.py --adapter blocked-mcp-preview --json
# Expect dispatch_allowed: false
```

Review:
- `docs/PHASE_3_0_BLOCKERS.md`
- `docs/PHASE_3_DESIGN_SPEC.md` §I (3.0 deliverables)
- `decisions/ADR-0012-phase-3-agent-dispatch-gates.md`

## Risks / Caveats
- Allowlist uses `shlex.split(posix=False)` on Windows — exotic quoting may need follow-up tests.
- Approval merge picks stricter of risk vs adapter level; blocked adapter status adds errors but explicit `--adapter blocked-mcp-preview` still builds partial preview.
- Preview writes only under `runtime/dispatch/` and `logs/dispatch-*.jsonl` — no task/handoff mutation.
- No agent execution, MCP, LLM APIs, secrets storage, or dashboard Run button in this phase.

## Recommended Next Action for Receiver
1. Review preview output shape and risk-gate integration against `docs/PHASE_3_READINESS_CRITERIA.md`.
2. Confirm ADR-0012 E2–E6 remain blocked (see `docs/PHASE_3_0_BLOCKERS.md`).
3. If approved, mark `T-PHASE3-0-PREVIEW` done and authorize Phase 3.1 execute-path design only (still no autonomous dispatch).