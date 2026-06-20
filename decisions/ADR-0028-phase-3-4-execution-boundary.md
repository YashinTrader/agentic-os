# ADR-0028: Phase 3.4 execution boundary

- Status: accepted
- Date: 2026-06-20
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/execution_gate.py`, `dispatch/executor.py`, ADR-0019, ADR-0022

## Context

Phase 3.4 adds worktree allocation and signed approvals. Execution boundaries from Phase 3.2 must remain intact.

## Decision

1. **Autonomy Level 1** — explicit `--execute` or `--dry-run` required; no scheduler changes.
2. **No real agents** — only `local-python-exec-test` has `supports_execution: true`.
3. **Subprocess isolation** — production `subprocess.run` only in `dispatch/executor.py`.
4. **Dashboard read-only** — no execute, approve, or allocate controls.
5. **Signed + allocated gates** — reviewer/human levels require valid HMAC; file-writing requires explicit allocation record.
6. **Operator-commanded allocation** — executor loads allocation via CLI flags; never auto-allocates.

## Consequences

- Positive: Phase 3.4 features add defense-in-depth without expanding autonomy.
- Negative: File-writing workflow requires three operator steps: allocate, sign approval, execute.
- Level 2+ scheduling remains future work per ADR-0022.