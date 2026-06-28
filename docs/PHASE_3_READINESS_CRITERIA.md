# Phase 3 Readiness Criteria

Gates that **must** be satisfied before Agentic OS allows agent dispatch (Phase 3).
Derived from ADR-0012. Phase 2.5 hardening does **not** implement these — it documents them.

## A. Execution gates

| Gate | Requirement | Phase 2 status |
|------|-------------|----------------|
| E1 | No automatic execution without an explicit operator command | ✅ Planning only |
| E2 | Dry-run mode required for every dispatch adapter | ⏳ Not implemented |
| E3 | Per-agent adapter must be allowlisted in registry | ⏳ Metadata only |
| E4 | Commands previewed before run (stdout/stderr plan) | ⏳ Plan JSON only |
| E5 | Timeout required on every subprocess dispatch | ⏳ Not implemented |
| E6 | Output captured to `logs/` JSONL + run artifacts | ⏳ Partial (events only) |
| E7 | Active task + handoff required before dispatch | ✅ Protocol exists |

## B. Approval gates

### Human approval required for

- Secrets / API keys access or storage
- Paid API spend
- External side effects (posts, emails, webhooks)
- CI / deploy triggers
- Production database read/write
- Destructive filesystem operations
- Merge to `main`
- Security / permission model changes

### Reviewer approval required for

- Protocol changes (`docs/AGENT_PROTOCOL.md`, task schema)
- Validator changes (`scripts/validate.py`)
- Registry changes (skills, MCPs, teams, roles)
- Agent adapter additions or behavior changes

Phase 2 orchestrator `risk_gate` surfaces human/reviewer/none heuristically but does **not** enforce dispatch.

## C. Sandbox gates

| Gate | Requirement | Phase 2 status |
|------|-------------|----------------|
| S1 | Repo-root containment for all writes | ✅ Orchestrator output-dir sandbox |
| S2 | No path traversal in task/output paths | ✅ `resolve_task_path`, `resolve_output_dir` |
| S3 | Git worktree isolation recommended for agents | ⏳ Documented, not enforced |
| S4 | No direct `main` branch mutation by agents | ✅ Policy only |

## D. Logging gates

Every dispatch run must have:

- `run_id` in state and artifacts
- Append-only JSONL event in `logs/agent-events.jsonl`
- Handoff file under `handoffs/`
- Links to `plan_path` and `context_pack_path` when planning preceded dispatch

Phase 2 orchestrator writes `orchestration_planned` events on successful finalize.

## E. Rollback gates

Before file-writing agent runs:

- Snapshot or branch pointer recorded in handoff
- Rollback instructions in handoff `## Risks / Caveats` or dedicated section
- Validator must not require snapshots (optional artifacts)

## Phase 3 go/no-go

**No-go** until E2–E6, adapter allowlisting, and approval enforcement are implemented with tests.

**Recommended sequence after Claude Phase 2 review:**

1. Dispatch adapter contract ADR + stub dry-run runner
2. Allowlist + preview CLI
3. Timeout + log capture
4. Human approval workflow integration
5. Worktree-isolated execution pilot

## Phase 3.0 follow-up (ADR-0013)

Phase 3.0 preview is complete per `decisions/ADR-0013-adapter-registry-schema.md`:

- Preview only — no subprocess, MCP, or LLM execution
- `forbidden_args` enforced at **token level** after `shlex.split`
- Missing or inactive adapter → `approval_level: blocked`, `approval_status: blocked`
- Generated artifacts gitignored: `runtime/dispatch/**`, `logs/dispatch-*.jsonl`
- `dispatch_allowed: true` is not execution permission

Phase 3.1 design (execute path, approval recording) requires a **separate ADR** and remains blocked.