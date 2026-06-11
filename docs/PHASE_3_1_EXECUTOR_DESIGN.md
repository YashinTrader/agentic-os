# Phase 3.1 — Controlled Executor Design (contract only)

**Status:** Design only — Phase 3.2 may implement if approved.  
**Related:** ADR-0014, ADR-0015, ADR-0016, `dispatch/executor_contract.py`

## Purpose

Define the controlled execution layer that Phase 3.2 can implement safely. Phase 3.1
delivers types, validators, schemas, and documentation — **no subprocess, agent, MCP, or
LLM execution**.

## Executor lifecycle (Phase 3.2 target)

| Step | Gate | Phase 3.1 artifact |
|------|------|-------------------|
| 1 | Load orchestration plan | `ExecutionPlanReference.plan_path` |
| 2 | Load adapter config | `agents/adapter_registry.yaml` |
| 3 | Verify adapter active and allowlisted | `validate_execution_request_contract` |
| 4 | Verify CLI inventory | `validate_cli_inventory_gate` |
| 5 | Verify command preview exists | `preview_path` required |
| 6 | Verify preview freshness | `dispatch/freshness.py` |
| 7 | Verify approval requirement | `approval_level` / `approval_status` |
| 8 | Verify approval record if required | `dispatch/approval_contract.py` |
| 9 | Verify worktree/sandbox policy | ADR-0016, `worktree_required` |
| 10 | Create execution `run_id` | `runtime/dispatch/runs/<run_id>/` |
| 11 | Capture stdout/stderr/logs in runtime only | Runtime capture contract |
| 12 | Write dispatch event logs | Reserved Phase 3.2 events |
| 13 | Require handoff | `handoff_path` mandatory |
| 14 | Never auto-merge | Hard invariant |
| 15 | Never mutate main branch | Hard invariant |

## Contract modules

| Module | Role |
|--------|------|
| `dispatch/executor_contract.py` | `ExecutionRequest`, validation, CLI gate |
| `dispatch/approval_contract.py` | Approval record shape and rules |
| `dispatch/freshness.py` | Preview hash and staleness |
| `dispatch/preview.py` | Phase 3.0 preview + KEY=VALUE allowlist |

## CLI inventory gate

Before any Phase 3.2 execution, the executor **must** verify:

1. Each `adapter.required_clis` entry exists in `runtime/registry/cli_inventory.yaml`.
2. Matching tool has `available: true`.
3. Matching tool has a non-empty `path`.
4. Missing or unavailable CLI → `execution_allowed: false` with explicit `blocked_reasons`.

Phase 3.1 provides `validate_cli_inventory_gate()` — read-only YAML load, no subprocess
to probe CLIs at validation time.

## KEY=VALUE allowlist extension

Token-level `forbidden_args` remains the default policy (ADR-0013). Phase 3.1 extends
preview validation:

- Tokens containing `=` are parsed into `(key, value)` via `parse_key_value_token`.
- Quoted values use `shlex.split` (same as token-level checks).
- **Forbidden keys** block regardless of value (e.g. `--execute=true` blocked when
  `--execute` is forbidden).
- **Forbidden exact tokens** still block standalone flags.
- **No substring matching** as primary policy.
- Malformed templates or shlex errors fail safe (warnings + conservative blocking).

See `validate_key_value_forbidden_args()` in `dispatch/preview.py`.

## Approval and freshness

Approvals are tied to `preview_hash` (ADR-0015). If the preview command, cwd, scope,
adapter, task, or approval/risk level changes, prior approvals are stale.

## Dashboard boundaries (Phase 3.1)

- Read-only design status may appear under Dispatch / Orchestrator tabs.
- **Forbidden:** Execute, Approve, Launch agent, Run MCP buttons.

## Phase boundaries

| Phase | Scope |
|-------|-------|
| 3.0 | Dry-run preview, `dispatch_allowed` |
| 3.1 | Executor contract, approval model, freshness, sandbox design |
| 3.2 | Implement executor runtime **only if** ADR-0014/0015/0016 accepted |

## Future event vocabulary (Phase 3.2 candidates)

Documented in `protocol/event_types.py` as `PHASE_3_2_EXECUTION_EVENT_TYPES` (reserved,
not in `ALLOWED_EVENT_TYPES` until emitters exist):

- `dispatch_approval_recorded`
- `dispatch_execution_requested`
- `dispatch_started`
- `dispatch_completed`
- `dispatch_failed`
- `dispatch_timed_out`
- `rollback_required`
- `handoff_required`