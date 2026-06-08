# ADR-0013: Adapter registry schema and Phase 3.0 dispatch preview contract

- Status: accepted
- Date: 2026-06-08
- Deciders: composer (implementer), claude (reviewer)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0012, agents/adapter_registry.yaml, dispatch/preview.py

## Context

Phase 3.0 introduces agent dispatch **preview only**. The adapter registry
(`agents/adapter_registry.yaml`) is load-bearing: it defines which CLIs may
appear in preview commands, default approval levels, dry-run support, and
forbidden argument tokens. Without a documented schema, Phase 3.1 executor work
would risk incompatible registry drift.

Phase 3.0 does **not** execute agents, subprocesses, MCP calls, or LLM APIs.
Execution remains blocked per ADR-0012 until a separate Phase 3.1 design ADR.

## Decision

### Registry location and validation

- Canonical registry: `agents/adapter_registry.yaml`
- Validator: `validate_adapter_registry()` in `scripts/validate.py`
- At least one `status: active` adapter required for preview readiness
- Active adapters **must** have `supports_dry_run: true`

### Required adapter fields (19)

| Field | Purpose |
|-------|---------|
| `id` | Stable adapter identifier |
| `display_name` | Human-readable label |
| `agent_id` | Maps to plan/task agent owner |
| `adapter_type` | `cli`, `mcp`, or `http` |
| `status` | `active`, `disabled`, or `planned` |
| `command_template` | Dry-run command with `{task_id}`, `{plan_path}`, etc. |
| `allowed_commands` | Allowlisted executable roots (e.g. `composer`, `codex`) |
| `forbidden_args` | Token-level forbidden flags (see below) |
| `required_clis` | CLIs that must exist before execution (Phase 3.1+) |
| `env_vars_required` | Env var names only (no values) |
| `secrets_required` | Boolean metadata — no secret storage in Phase 3.0 |
| `timeout_seconds` | Declared timeout for future executor |
| `working_directory_policy` | `repo_root`, `worktree`, or `task_subdir` |
| `supports_dry_run` | Must be true for active adapters in Phase 3.0 |
| `supports_streaming` | Future executor hint |
| `writes_files` | Triggers rollback strategy text in preview |
| `approval_level` | Default gate: `none`, `reviewer`, `human`, `blocked` |
| `risk_level` | `low`, `medium`, `high` — informational + validator |
| `notes` | Free-form documentation |

### Active vs inactive behavior

- **active** — eligible for automatic selection by `agent_id`; preview may set
  `dispatch_allowed: true` when all other gates pass.
- **disabled** / **planned** — never auto-selected; explicit `--adapter` still
  resolves the entry but preview sets `approval_level: blocked`,
  `approval_status: blocked`, and `dispatch_allowed: false`.

### Dry-run and preview contract

- `dispatch/preview.py` expands templates, runs allowlist checks, merges risk
  gate + adapter approval, and returns JSON with `executed: false`,
  `mode: dry_run_preview`.
- `scripts/preview_dispatch.py` writes artifacts under `runtime/dispatch/` and
  append-only lines under `logs/dispatch-<timestamp>.jsonl` (run_id prefix).
- No subprocess, MCP, or LLM invocation in Phase 3.0.

### `forbidden_args` policy (token-level)

After `shlex.split` (with safe whitespace fallback on parse errors),
forbidden args match **exact command tokens** (case-insensitive):

- `--execute` matches token `--execute`
- `not--dangerous-text` does **not** match forbidden `--danger`
- Quoted tokens are parsed before comparison

Substring matching is **not** used. Phase 3.1 executor must reuse the same
token-level check before any subprocess.

### `approval_level` / `risk_level` usage

- `orchestrator.risk.evaluate_risk()` produces the risk gate result.
- `merge_approval_gate()` picks the stricter of risk vs adapter default.
- When no active adapter is selected, `resolve_approval_gate()` returns
  `approval_level: blocked` and `approval_status: blocked` with an explicit
  adapter-selection reason (no ambiguous `human` + `blocked` pairs).

### `dispatch_allowed` semantics

`dispatch_allowed: true` means the preview is internally well-formed and could
be presented to a future executor. It does **not** mean execution may proceed.
Phase 3.1+ must additionally check `approval_gate.approval_status`, recorded
approvals, and preview freshness.

### Phase 3.1 boundary

This ADR covers preview only. `scripts/execute_dispatch.py`, subprocess
sandboxing, approval recording, timeout enforcement, and execution event types
require a **separate Phase 3.1 design ADR** and remain blocked until accepted.

## Consequences

**Positive**

- Registry schema is versioned, validator-enforced, and documented.
- Token-level forbidden args reduce false positives before executor lands.
- Blocked adapter states are unambiguous for Phase 3.1 consumers.

**Negative**

- Registry edits require validator + reviewer review.
- Inactive adapters remain in registry for documentation but cannot preview as allowed.

**Neutral**

- `required_clis` cross-check against CLI inventory deferred to Phase 3.1 design.

## Sign-off

- [x] composer (proposer/implementer)
- [x] claude (reviewer — Phase 3.0 review 2026-06-08)