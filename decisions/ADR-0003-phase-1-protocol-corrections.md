# ADR-0003: Phase 1 Protocol Corrections and Retroactive Approval of Validator Dependency

**Status:** accepted
**Date:** 2026-05-23
**Author (agent):** claude
**Reviewer (agent):** human
**Approval:** human   # required: introduces a top-level dependency (PyYAML)

## Context
During Codex's first Phase 1 implementation pass, the validator script
(`scripts/validate.py`) was added together with `requirements.txt` declaring
`PyYAML` as a dependency.

This satisfied the technical intent of backlog task **T-0008** but bypassed
two explicit procedural rules:

1. `tasks/PHASE_1_TASKS.md` requires an ADR before T-0008 begins ("Requires
   ADR for adopting Python as the validator language").
2. `docs/AGENT_PROTOCOL.md` §5 lists "Installing new top-level dependencies or
   changing build/CI config" as a **risky action** requiring an ADR with
   `approval: human`.

In addition, the Claude review identified several minor schema/doc
inconsistencies that should be resolved before T-0001..T-0005 are archived.

This ADR captures both the **retroactive approval** of the validator
dependency and the **set of corrective fixes** Codex must apply.

## Decision

### Part A — Retroactively approve `PyYAML` as a Phase 1 dependency
- **Language:** Python 3 (already assumed by typical agent toolchains).
- **Dependency:** `PyYAML` only. No additional packages without a new ADR.
- **Scope:** Used exclusively by `scripts/validate.py` for local validation
  of task YAML files. Not used by any agent at runtime.
- **Install path:** `pip install -r requirements.txt`. No global installs.
- **Sunset clause:** When/if Phase 2 introduces a richer schema validator
  (e.g. `pydantic`, JSON-schema), this ADR is superseded.

### Part B — Adopt the Phase 1 Protocol Corrections
Codex must apply the following before T-0001..T-0003 are moved to
`tasks/done/`:

1. Update `tasks/PHASE_1_TASKS.md`:
   - T-0008 → status `review` (no longer `todo`).
   - Add T-0011 row for "Apply Phase 1 review corrections" (owner `codex`).
2. Add a minimal `tasks/active/T-0008.yaml` with `status: review` so the
   validator work has a corresponding task file (currently missing).
3. Fix `tasks/active/EXAMPLE.yaml`:
   - Change `id: T-0000` → `id: T-EXAMPLE` (frees T-0000 for the bootstrap
     log event exclusively).
   - Change `outputs: - (this file is itself the output)` to
     `outputs: - tasks/active/EXAMPLE.yaml`.
4. Reconcile `docs/ARCHITECTURE.md` §3:
   - Either restore Unicode box-drawing characters in the tree, **or**
   - Adjust T-0001 acceptance criterion to "directory set matches §3"
     (not "tree -L 2 matches §3").
   Recommendation: option (a) — restore Unicode.
5. Add `related_handoff: handoffs/T-0001__codex__to__claude.md` (or a line in
   `handoff_notes`) to `T-0002.yaml`, `T-0003.yaml`, and the new `T-0008.yaml`
   so the bundled-handoff link is explicit.
6. Re-run `python scripts/validate.py` and confirm exit 0.
7. Close T-0010 (Claude review) by referencing this ADR and
   `docs/REVIEW_CLAUDE_PHASE_1.md`.

### Part C — Procedural lesson logged
Going forward: **no agent installs a dependency, modifies a schema doc, or
touches CI config without an `approval: human` ADR pre-merge.** Codex's first
pass is forgiven; the second is not.

## Alternatives Considered
1. **Reject the validator and require resubmission with a pre-approved ADR.**
   Rejected: punitive, wastes good work, slows Phase 1 with no upside.
2. **Drop PyYAML; rewrite the validator in pure stdlib.** Rejected: would
   require a hand-rolled YAML subset parser; high bug risk for low gain.
3. **Defer all corrections to Phase 2.** Rejected: leaves the backlog in a
   stale/contradictory state; violates Phase 1 success criterion #1 (a new
   agent can self-onboard).

## Consequences
- **Pro:** Codex's work lands cleanly; protocol authority preserved by
  recording the violation rather than ignoring it.
- **Pro:** Future agents see a worked example of how a procedural slip is
  remediated via an ADR, reinforcing the "no silent decisions" rule.
- **Con:** Adds one cleanup task (T-0011) before Phase 1 can close.
- **Con:** Sets a precedent for retroactive approvals — must be used
  sparingly. Repeated retroactive approvals would erode the protocol.

## References
- `docs/REVIEW_CLAUDE_PHASE_1.md` (this ADR's companion review)
- `docs/AGENT_PROTOCOL.md` §5 (Risky Actions)
- `tasks/PHASE_1_TASKS.md` (T-0008, T-0011)
- `scripts/validate.py`
- `requirements.txt`
- `handoffs/T-0001__codex__to__claude.md`

---

Approved-by: Gabriel Achim on 2026-05-23
