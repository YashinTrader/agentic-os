# Phase 3 Design Spec

**Status:** design only — no implementation in Phase 2.6  
**Related:** ADR-0012, `docs/PHASE_3_READINESS_CRITERIA.md`, `docs/REVIEW_CLAUDE_PHASE_2.md`

## A. Purpose

Phase 3 moves Agentic OS from **planning-only orchestration** toward **controlled
agent dispatch** without losing the file-based safety model established in Phases
1–2.

Goals:

- Turn orchestrator plans into previewable, gated dispatch commands.
- Introduce adapter contracts before any execution code ships.
- Preserve human/reviewer approval boundaries from the fixed risk gate (Phase 2.6).
- Keep Git-as-bus, append-only logs, and handoff protocol as the audit trail.

Phase 3.0 does **not** run agents. It builds dry-run command preview and gates.

## B. Non-goals

- No autonomous agent swarm or scheduling loops.
- No silent subprocess execution from dashboard or orchestrator.
- No paid API calls without explicit human approval.
- No secrets storage, rotation, or vault integration.
- No MCP tool invocation without allowlist + approval.
- No direct `main` branch mutation by adapters.
- No database or external message bus.

## C. Dispatch lifecycle

```
1. load plan          ← runtime/orchestrator/latest_plan.json + context pack
2. select adapter     ← agents/adapter_registry.yaml by team/agent id
3. check allowlist    ← adapter id + command template in registry
4. generate preview   ← dispatch/preview.py expands template with task context
5. risk gate          ← orchestrator/risk.py (fixed precedence)
6. approval gate      ← human | reviewer | none | blocked
7. dry-run output     ← stdout plan only; no subprocess
8. [future] execute   ← Phase 3.2+ behind explicit operator command
9. capture logs       ← logs/dispatch-<run_id>.jsonl
10. write handoff     ← handoffs/<task>__<agent>__to__<receiver>.md
11. update task       ← only via scripts/update_task.py when permitted
```

Phase 3.0 stops after step 7. Steps 8–11 are specified but not implemented.

## D. Agent adapter interface

Proposed registry: `agents/adapter_registry.yaml`

```yaml
adapters:
  - id: codex-cli-readonly
    display_name: Codex CLI (read-only preview)
    adapter_type: cli
    command_template: "codex --dry-run --task {task_id}"
    allowed_commands: ["codex"]
    forbidden_args: ["--execute", "--apply", "--force"]
    required_clis: ["codex"]
    timeout_seconds: 300
    working_directory_policy: repo_root
    supports_dry_run: true
    supports_streaming: false
    writes_files: false
    approval_level: reviewer
    risk_level: medium
```

Fields:

| Field | Purpose |
|-------|---------|
| `id` | Allowlist key |
| `adapter_type` | `cli`, `mcp`, `http` (future) |
| `command_template` | Preview string with `{task_id}`, `{plan_path}` placeholders |
| `allowed_commands` | Binary allowlist roots |
| `forbidden_args` | Args that block preview/execution |
| `required_clis` | Must appear in `runtime/registry/cli_inventory.yaml` |
| `timeout_seconds` | Hard cap for future execution |
| `working_directory_policy` | `repo_root`, `worktree`, `task_subdir` |
| `supports_dry_run` | Must be true for Phase 3.0 |
| `writes_files` | Triggers snapshot/rollback requirements |
| `approval_level` | Default gate if risk gate returns none |

## E. Dry-run command preview

`scripts/preview_dispatch.py` (Phase 3.0) must print:

| Item | Required |
|------|----------|
| Resolved command | yes |
| Working directory | yes |
| Files/directories in scope | yes |
| Timeout | yes |
| Environment variables (names only) | yes |
| Secrets required | yes/no flag only |
| Expected outputs | yes |
| Logs path | `logs/dispatch-<run_id>.jsonl` |
| Handoff path | proposed path |
| Rollback strategy | text for file-writing adapters |
| Risk gate result | `approval_level` + reason |
| Approval gate result | pending human/reviewer/none |

No subprocess invocation in Phase 3.0.

## F. Approval gates

Reuse `docs/PHASE_3_READINESS_CRITERIA.md` §B.

Explicit rules:

- **Reviewer** required for adapter config changes, registry changes, protocol/validator changes.
- **Human** required when risk gate returns `human` or `blocked`.
- **None** allowed for read-only preview of low-risk plans.
- Dashboard may display preview only — no execute button until Phase 3.2.

## G. Sandbox / worktree strategy

- Every dispatch run gets a unique `run_id` (same pattern as orchestrator).
- Default working directory: repository root.
- File-writing adapters (Phase 3.2+): Git worktree per run recommended.
- Path containment: all reads/writes under repo root or declared worktree.
- No adapter may target `main` directly — branch-per-task policy.

## H. Event vocabulary for Phase 3 (proposed, not canonical yet)

Future types (add to `protocol/event_types.py` only when emitters land):

| type | when |
|------|------|
| `dispatch_preview_created` | dry-run preview written |
| `dispatch_blocked` | gate blocked dispatch |
| `dispatch_approved` | human/reviewer approval recorded |
| `dispatch_started` | execution begins (Phase 3.2+) |
| `dispatch_completed` | execution succeeded |
| `dispatch_failed` | execution failed |
| `handoff_required` | dispatch cannot proceed without handoff |

## I. Phase 3.0 deliverables

Implementation scope (next task after design acceptance):

- `agents/adapter_registry.yaml` — stub adapters, dry-run only
- `dispatch/preview.py` — template expansion + gate checks
- `scripts/preview_dispatch.py` — CLI entry
- Dashboard **Dispatch Preview** tab (read-only)
- Tests: preview output, allowlist rejection, risk-gate integration
- ADR for adapter contract

No execution subprocess. No MCP calls.

## J. Phase 3.1 deliverables

- Controlled **manual** execution with explicit operator command
- Timeout + stdout/stderr capture to `logs/`
- Handoff required before and after run
- Still no autonomous scheduling

## K. Phase 3.2+ deliverables

- Adapter execution behind double confirmation (CLI flag + approval)
- MCP execution with per-adapter allowlist
- Worktree isolation for file-writing agents
- Budget/spend tracking hooks (human approval for paid APIs)
- Agent monitoring and stall detection (ties to loop-operator patterns)