# Phase 3.2 Review Packet (Claude)

**Task:** T-PHASE3-2-EXECUTOR  
**Branch:** `agent/composer/T-PHASE3-2-CONTROLLED-EXECUTOR`  
**Commit message:** `T-PHASE3-2: add controlled executor MVP with safety gates`

## Review Checklist

- [ ] **No autonomous execution** — orchestrator/dashboard/daemon do not run dispatch
- [ ] **Explicit operator command only** — `execute_dispatch.py` requires `--dry-run` or `--execute`
- [ ] **Preview freshness** — `is_preview_stale` / hash mismatch blocks
- [ ] **Approval record correctness** — shape vs satisfaction split; TTL defaults 30/60 min
- [ ] **CLI inventory gate** — enforced in executor (`execution_gate`), not preview-only
- [ ] **Timeout / log capture** — subprocess timeout; stdout/stderr/result/events written
- [ ] **Worktree policy** — writes_files without worktree blocked; path traversal blocked
- [ ] **Dashboard read-only boundary** — no Execute/Approve/Launch/Run agent UI
- [ ] **Event vocabulary** — emitted types in `ALLOWED_EVENT_TYPES`; unknown rejected
- [ ] **Tests and validator** — `python scripts/run_tests.py` and `python scripts/validate.py` pass

## Key Files

| Area | Path |
|------|------|
| Executor | `dispatch/executor.py` |
| Gates | `dispatch/execution_gate.py` |
| Approval store | `dispatch/approval_store.py` |
| Runtime capture | `dispatch/runtime_capture.py` |
| Worktree policy | `dispatch/worktree_policy.py` |
| CLI execute | `scripts/execute_dispatch.py` |
| CLI approve | `scripts/approve_dispatch.py` |
| Safe adapter | `agents/adapter_registry.yaml` → `local-python-exec-test` |
| ADRs | `decisions/ADR-0017` … `ADR-0019` |
| Self-review | `docs/REVIEW_COMPOSER_PHASE_3_2_SELF_REVIEW.md` |

## Verification Commands

```bash
python scripts/run_tests.py
python scripts/validate.py
rg "subprocess" dispatch/ dashboard/ orchestrator/ scripts/preview_dispatch.py
rg -i "Execute|Approve|Launch|Run agent" dashboard/app.py
```

## Out of Scope (must not appear)

- Phase 3.3 autonomous scheduler
- Dashboard execution buttons
- MCP/LLM API calls in executor path