# Phase 3.1 — Approval Recording Model

**Status:** Design only  
**Related:** ADR-0015, `dispatch/approval_contract.py`, `schemas/approval_record.schema.json`

## Approval record fields

| Field | Type | Purpose |
|-------|------|---------|
| `approval_id` | string | Unique approval identifier |
| `task_id` | string | Task being approved for execution |
| `run_id` | string | Dispatch run identifier |
| `preview_hash` | string | SHA-256 of canonical preview payload |
| `adapter_id` | string | Adapter under approval |
| `approval_level` | enum | `none`, `reviewer`, `human`, `blocked` |
| `approved_by` | string | Human or agent identifier (opaque string) |
| `approver_type` | enum | `human`, `reviewer`, `system` |
| `approved_at` | ISO-8601 | When approval was recorded |
| `expires_at` | ISO-8601 | Required for human/reviewer approvals |
| `scope` | string | Short description of approved scope |
| `allowed_command_hash` | string | Optional secondary digest of command only |
| `allowed_cwd` | string | Approved working directory |
| `allowed_scope_paths` | string[] | Path allowlist snapshot |
| `notes` | string | Free-form reviewer notes |
| `revoked` | boolean | When true, approval is invalid |

## Rules

1. **Preview binding** — Approval is tied to `preview_hash`. If the preview changes,
   approval is stale (`is_approval_fresh` returns false).
2. **Human for high-risk** — `secrets_required`, production deploy patterns, and
   `approval_level: human` require `approver_type: human`.
3. **Reviewer sufficient** — Registry, validator, and protocol changes may use
   `approver_type: reviewer` when `approval_level: reviewer`.
4. **Preview-only exempt** — Phase 3.0 dry-run preview (`mode: dry_run_preview`) does
   not require an approval record.
5. **System cannot approve human-level** — `approver_type: system` is rejected for
   `approval_level: human`.
6. **Expiry required** — Human and reviewer approvals must include `expires_at` in the
   future at validation time.
7. **Revocation** — `revoked: true` invalidates immediately.
8. **Default TTL** — Human approvals default to **30 minutes**; reviewer approvals default
   to **60 minutes** (`DEFAULT_HUMAN_APPROVAL_TTL_MINUTES` /
   `DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES` in `dispatch/approval_contract.py`). Adapters
   may override per-registry in Phase 3.2.

## Validation API (Phase 3.1 cleanup)

Two separate concepts (do not mix shape and satisfaction):

| Function | Purpose |
|----------|---------|
| `validate_approval_record_shape(record)` | Required fields, types, ISO-8601 expiry format |
| `evaluate_approval_satisfaction(record, preview_hash, required_level, now)` | Whether execution approval is satisfied |

`evaluate_approval_satisfaction` returns:

- `satisfied: bool`
- `status`: `none` \| `pending` \| `approved` \| `blocked` \| `stale` \| `expired` \| `revoked` \| `invalid`
- `reasons: list[str]`

Rules:

- `required_approval_level: none` — no record required (`status: none`, `satisfied: true`).
- `blocked` — never satisfied.
- `human` required — only `approver_type: human` satisfies.
- `reviewer` required — `reviewer` or `human` satisfies.
- `preview_hash` mismatch — `status: stale`.
- Expired / revoked / malformed — `expired` / `revoked` / `invalid` respectively.

## Storage (Phase 3.2)

Runtime path: `runtime/dispatch/runs/<run_id>/approval_record.json`

Phase 3.1 defines validation only — no auth system, no cryptographic signing, no
approval UI.

## Freshness helpers

- `compute_preview_hash(preview)` — canonical JSON SHA-256
- `is_approval_fresh(preview_hash, approval_record, required_approval_level)` — delegates to `evaluate_approval_satisfaction`
- `is_preview_stale(preview, current_adapter, current_task, current_plan)` — live drift

See `dispatch/freshness.py`.