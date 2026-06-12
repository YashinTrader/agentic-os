# Phase 3.2 Controlled Executor MVP

**Status:** implemented (pending Claude final review)  
**Branch:** `agent/composer/T-PHASE3-2-CONTROLLED-EXECUTOR`

## Purpose

Deliver the first **operator-commanded**, **preview-first**, **approval-gated**
dispatch executor. No autonomous scheduling. No dashboard execution.

## Execution Lifecycle

1. **Preview** — `scripts/preview_dispatch.py` builds dry-run preview (Phase 3.0).
2. **Approve** (if required) — `scripts/approve_dispatch.py` writes approval record.
3. **Dry-run executor** — `execute_dispatch.py --dry-run` validates all gates, writes artifacts, no subprocess.
4. **Explicit execute** — `execute_dispatch.py --execute` runs subprocess only when all gates pass and adapter has `supports_execution: true`.

Gate order (see `dispatch/execution_gate.py`):

- Operator flag (`--dry-run` or `--execute`)
- Adapter active, allowlisted, supports dry-run
- For `--execute`: adapter `supports_execution: true`
- CLI inventory available (enforced in executor, not preview)
- Preview freshness
- Approval satisfaction
- Command allowlist / forbidden args
- Timeout present and within max (3600s)
- Worktree/sandbox policy
- `secrets_required` / `mcp_required` policy
- High-risk human approval

## CLI Commands

```bash
# Preview (no execution)
python scripts/preview_dispatch.py --adapter local-python-exec-test --json

# Approval record only
python scripts/approve_dispatch.py \
  --preview runtime/dispatch/previews/<run_id>/preview.json \
  --level reviewer --approved-by operator

# Dry-run executor (gates only)
python scripts/execute_dispatch.py \
  --preview runtime/dispatch/previews/<run_id>/preview.json \
  --dry-run

# Explicit safe test execution
python scripts/execute_dispatch.py \
  --preview runtime/dispatch/previews/<run_id>/preview.json \
  --execute
```

Human approval requires `--approver-type human --approved-by "<name>"`.

## Approval Model

- Shape validation: `validate_approval_record_shape`
- Satisfaction: `evaluate_approval_satisfaction`
- Default TTLs: human 30 min, reviewer 60 min (ADR-0015)
- Records stored at `runtime/dispatch/approvals/<approval_id>.json`

## Worktree / Sandbox Model

- Preview `worktree_required` is **advisory**
- Executor enforces via `dispatch/worktree_policy.py`
- File-writing execution requires configured worktree (MVP blocks if missing)
- `cwd` and `scope_paths` must resolve inside repo or approved worktree

## Runtime Outputs

Per run: `runtime/dispatch/runs/<run_id>/`

- `execution_request.json`, `preview.json`, `approval_record.json` (if used)
- `stdout.log`, `stderr.log`, `result.json`, `events.jsonl`
- `rollback.md`, `handoff_required.md`

Latest pointers: `runtime/dispatch/latest_execution_request.json`, `latest_result.json`

## Safety Guarantees

- Subprocess only in `dispatch/executor.py`
- No MCP / LLM / secrets access in executor path
- No task owner/status mutation
- No auto-merge / auto-push
- Real agent adapters preview-only (`supports_execution` false/absent)

## Remains Blocked

- Autonomous agent scheduling (Phase 3.3+)
- MCP execution (policy `mcp_execution_allowed=false`)
- File-writing execution without worktree
- Codex/Claude/Gemini/Composer CLI live execution
- Dashboard/orchestrator execution