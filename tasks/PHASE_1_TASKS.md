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
| T-0012 | Phase 1.5 minimal CLI task runner                  | codex  | done   | low  |
| T-0015 | Migrate repository to task schema v2               | codex  | review | med  |
| T-0016 | Update CLI helpers to write task schema v2         | codex  | review | low  |

## Task Details

### T-0016 - Update CLI helpers to write task schema v2
- **Objective:** Update the Phase 1.5 task CLI helpers so newly created or
  updated task YAML files use task schema v2 by default after the T-0015
  migration.
- **Outputs:** `scripts/create_task.py`, `scripts/update_task.py`,
  `tests/test_phase15_cli.py`, `tasks/active/T-0016.yaml`,
  `handoffs/T-0016__codex__to__claude.md`.
- **Acceptance:** `create_task.py` emits v2 field names; `update_task.py`
  preserves/upgrades v2 fields when moving tasks; `python -m unittest -v
  tests.test_phase15_cli` and `python scripts/validate.py` exit 0.

## Exit Criteria for Phase 1
- Non-deferred Phase 1 tasks are done.
- Validator green on `main`.
- A new agent can be onboarded by reading `README.md` + `docs/` only.
- Codex has independently produced at least one valid handoff loop.
- T-0009 remains deferred until a separate ADR and human approval.
- Phase 1.5 CLI helpers are available for local file-based task operations.
