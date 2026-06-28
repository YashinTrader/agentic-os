# Phase 3.0 — Remaining Blockers for Real Agent Execution

Phase 3.0 delivers **dry-run dispatch preview only**. The following ADR-0012 gates (E2–E6) remain **not implemented** for live execution.

## Gate status (ADR-0012)

| Gate | Requirement | Phase 3.0 status |
|------|-------------|------------------|
| E2 | Explicit execute command (`execute_dispatch.py` or equivalent) | **Not implemented** — only `preview_dispatch.py` |
| E3 | Dry-run mode before real run | **Preview only** — no execution path |
| E4 | Command allowlist + forbidden args | **Implemented in preview** — not enforced at runtime |
| E5 | Preview-before-run (preview artifact required) | **Partial** — preview JSON written; no execute gate |
| E6 | Timeout, logging, handoff, rollback | **Partial** — metadata in preview; no runtime enforcement |

## Additional blockers

1. **No subprocess execution** — `dispatch/preview.py` must not invoke agents; Phase 3.1+ needs a separate executor module with human/reviewer approval checks.
2. **No MCP invocation** — `blocked-mcp-preview` adapter is disabled; MCP tools are not callable.
3. **No secrets storage** — `secrets_required` is metadata only; no vault integration.
4. **No paid API / LLM calls** — adapters reference CLIs only; no API keys or billing paths.
5. **No dashboard execute controls** — Dispatch Preview tab is read-only; no Run/Approve buttons.
6. **No automatic task mutation** — preview does not change task owner, status, or handoff files.
7. **Human approval workflow** — high-risk tasks surface `pending_human` in preview but have no approval UI or signed approval record.
8. **Rollback / worktree** — `writes_files: true` adapters document rollback strategy; no snapshot or git worktree automation.
9. **CLI availability** — `required_clis` are not verified at preview time (discovery registry is separate).
10. **Execution events** — `dispatch_started`, `dispatch_completed`, `dispatch_failed` remain reserved, not emitted.

## Safe next step (Phase 3.1)

Per `docs/PHASE_3_DESIGN_SPEC.md` §J:

- Add `scripts/execute_dispatch.py` behind explicit `--execute` flag only.
- Require existing preview artifact and matching `run_id` / `task_id`.
- Re-run risk gate and block if `approval_level: human` without recorded approval.
- Bounded timeout + structured log append only (no autonomous scheduling).

## Verification commands (Phase 3.0)

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/validate.py
python scripts/preview_dispatch.py --json
```