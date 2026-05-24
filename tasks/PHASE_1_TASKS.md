# Phase 1 - Task Backlog

All tasks below are the minimum scope to make the file-based control plane
real and usable. Codex is the primary implementer. Claude reviews.

Status legend: ready | in_progress | review | done | blocked

| ID     | Title                                              | Owner  | Status | Risk |
|--------|----------------------------------------------------|--------|--------|------|
| T-0001 | Initialize repo skeleton (dirs + README)           | codex  | done   | low  |
| T-0002 | Commit docs/ (ARCHITECTURE, AGENT_PROTOCOL, etc.)  | codex  | done   | low  |
| T-0003 | Create tasks/active, done, blocked directories     | codex  | done   | low  |
| T-0004 | Write tasks/active/EXAMPLE.yaml reference template | codex  | done   | low  |
| T-0005 | Create logs/agent-events.jsonl with first event    | codex  | done   | low  |
| T-0006 | Create decisions/INDEX.md + ADR-0001, ADR-0002     | claude | done   | low  |
| T-0007 | Write handoffs/ directory README + first handoff   | codex  | done   | low  |
| T-0008 | Add validator script: `scripts/validate.py`        | codex  | done   | med  |
| T-0009 | CI: GitHub Action runs validator on every PR       | codex  | todo   | med  |
| T-0010 | Claude review of full Phase 1 (produces ADR-0003)  | claude | done   | low  |
| T-0011 | Apply Claude's Phase 1 review corrections          | codex  | done   | low  |
| T-0012 | Phase 1.5 minimal CLI task runner                  | codex  | review | med  |
| T-0012a| CLI guardrails, schema-v2 writers, T-0012 rollback | codex  | review | med  |
| T-0015 | Migrate repository to task schema v2               | codex  | review | med  |
| T-0013 | Read-only Phase 1.6 dashboard for schema v2        | antigravity | ready  | low  |
| T-0017 | Librarian agent implementation                     | antigravity | ready  | med  |
| T-0018 | MCP adapter implementation                         | antigravity | ready  | med  |
| T-0019 | Agent persona/voice scaffolding                    | antigravity | ready  | low  |

## Task Details


### T-0001 - Initialize repo skeleton
- **Objective:** Create top-level directories and README.
- **Outputs:** `README.md`, `docs/`, `tasks/`, `handoffs/`, `decisions/`, `logs/`, `memory/`.
- **Acceptance:** `tree -L 2` matches `ARCHITECTURE.md` section 3.

### T-0002 - Commit docs/
- **Objective:** Land all five docs verbatim from the Manager-Architect plan.
- **Outputs:** `docs/ARCHITECTURE.md`, `docs/AGENT_PROTOCOL.md`, `docs/TASK_SCHEMA.md`, `docs/HANDOFF_PROTOCOL.md`, `docs/DECISIONS.md`.
- **Acceptance:** All files render cleanly on GitHub.

### T-0003 - Tasks directories
- **Objective:** Create `tasks/active/`, `tasks/done/`, `tasks/blocked/` with `.gitkeep`.
- **Acceptance:** Directories tracked in Git.

### T-0004 - EXAMPLE.yaml
- **Objective:** A reference task file demonstrating every required + optional field.
- **Acceptance:** Validates against `TASK_SCHEMA.md`; reviewed by Claude.

### T-0005 - Event log seed
- **Objective:** Create `logs/agent-events.jsonl` with one bootstrap event.
- **Acceptance:** File exists; first line is valid JSON per `AGENT_PROTOCOL.md` section 6.

### T-0006 - Decisions seed (Claude)
- **Objective:** Write ADR-0001 ("Use Git repo as message bus") and
  ADR-0002 ("YAML for task files") and populate INDEX.md.
- **Owner:** claude.
- **Acceptance:** Two ADRs accepted; INDEX up to date.

### T-0007 - Handoffs seed
- **Objective:** `handoffs/README.md` explaining the directory + first real
  handoff from codex to claude for T-0002.
- **Acceptance:** Handoff conforms to `HANDOFF_PROTOCOL.md`.

### T-0008 - Validator script
- **Objective:** `scripts/validate.py` checks: task YAML schema, event log
  JSONL validity, ADR front-matter, handoff required sections.
- **Risk:** medium (introduces a dependency: Python + PyYAML).
- **Acceptance:** Script exits 0 on a clean repo; non-zero on injected errors.
- **Requires ADR** for adopting Python as the validator language. ADR-0003 is
  accepted with human sign-off from Gabriel Achim.

### T-0009 - CI hook
- **Objective:** GitHub Action runs `validate.py` on every PR.
- **Risk:** medium (CI config change; see `AGENT_PROTOCOL.md` section 5).
- **Acceptance:** A bad task file blocks PR merge.
- **Requires ADR + human approval.**
- **Status:** Deferred until explicitly requested.

### T-0010 - Claude Phase-1 review
- **Objective:** Read everything, produce ADR-0003 with any corrections or
  approvals. Mark Phase 1 complete.
- **Acceptance:** ADR-0003 accepted and review filed in `docs/REVIEW_CLAUDE_PHASE_1.md`.
- **Status:** Done after Claude approval and human sign-off from Gabriel Achim.

### T-0011 - Apply Claude's Phase 1 review corrections
- **Objective:** Apply the cleanup items from `docs/REVIEW_CLAUDE_PHASE_1.md`
  without schema, protocol, validator, dependency, CI, or directory changes.
- **Outputs:** `tasks/done/T-0011.yaml`, `tasks/done/T-0008.yaml`,
  `handoffs/T-0011__codex__to__claude.md`, updated backlog and log.
- **Acceptance:** Validator remains green and handoff summarizes the diffs.

### T-0012 - Phase 1.5 minimal CLI task runner
- **Objective:** Add small file-based helpers for creating/listing/updating
  tasks, appending log events, and creating handoffs.
- **Outputs:** `scripts/create_task.py`, `scripts/list_tasks.py`,
  `scripts/update_task.py`, `scripts/append_log.py`,
  `scripts/create_handoff.py`, `tests/test_phase15_cli.py`.
- **Acceptance:** `python -m unittest` and `python scripts/validate.py` exit 0.
- **Status:** Rolled back to `review` by T-0012a under ADR-0003.

### T-0012a - CLI guardrails, schema-v2 writers, and T-0012 rollback
- **Objective:** Update CLI writers to emit schema v2 and ADR-0004 events, add
  ADR-0003 guardrails, and roll T-0012 back to review.
- **Outputs:** `scripts/create_task.py`, `scripts/update_task.py`,
  `scripts/create_handoff.py`, `scripts/append_log.py`,
  `tests/test_cli_guardrails.py`, `tasks/active/T-0012.yaml`,
  `handoffs/T-0012a__codex__to__claude.md`.
- **Acceptance:** Validator and full unittest suite exit 0.

### T-0015 - Migrate repository to task schema v2
- **Objective:** Apply ADR-0005 by updating the schema doc, validator, and task YAML files.
- **Outputs:** `docs/TASK_SCHEMA.md`, `scripts/validate.py`,
  `scripts/migrate_schema_v2.py`, all task YAML files, `docs/AGENT_PROTOCOL.md`,
  `logs/agent-events.jsonl`, `handoffs/T-0015__codex__to__claude.md`.
- **Acceptance:** Migration is idempotent; validator accepts v1 with warnings
- **Status:** Review after Codex implementation and human approval of ADR-0005.

### T-0013 - Read-only Phase 1.6 dashboard for schema v2
- **Objective:** Build a local, read-only dashboard that renders the current task ledger, recent events, and open handoffs directly from the repo files.
- **Outputs:** `dashboard/` directory, `tests/test_dashboard.py`, `handoffs/T-0013__antigravity__to__human.md`.
- **Acceptance:** Validator is clean, unittest suite green, dashboard renders correctly under standard standard library server on schema v2 files and ADR-0004 events.

### T-0017 - Librarian agent implementation (Phase 2 Placeholder)
- **Objective:** Implement the Librarian agent which observes other agents' events/handoffs and standardizes memory operations.
- **Status:** Placeholder (do not start yet).

### T-0018 - MCP adapter implementation (Phase 2 Placeholder)
- **Objective:** Implement the Model Context Protocol (MCP) adapter read/write contract to interface the control plane with our memory backend.
- **Status:** Placeholder (do not start yet).

### T-0019 - Agent persona/voice scaffolding (Phase 2 Placeholder)
- **Objective:** Establish the per-agent persona YAML definitions, capabilities registry, and system prompts to configure agent voices.
- **Status:** Placeholder (do not start yet).

## Schema v2 Rename Map

ADR-0005 migrates task YAML from v1 to v2:

| v1                    | v2                 |
|-----------------------|--------------------|
| `created`             | `created_at`       |
| `updated`             | `updated_at`       |
| `acceptance_criteria` | `acceptance`       |
| `handoff_notes`       | `notes`            |
| `priority: P0`        | `priority: high`   |
| `priority: P1`        | `priority: high`   |
| `priority: P2`        | `priority: medium` |
| `priority: P3`        | `priority: low`    |
| `status: todo`        | `status: ready`    |

## Exit Criteria for Phase 1
- Non-deferred Phase 1 tasks are done.
- Validator green on `main`.
- A new agent can be onboarded by reading `README.md` + `docs/` only.
- Codex has independently produced at least one valid handoff loop.
- T-0009 remains deferred until a separate ADR and human approval.
- Phase 1.5 CLI helpers are available for local file-based task operations.
