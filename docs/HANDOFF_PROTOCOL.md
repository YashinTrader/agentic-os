# Handoff Protocol (v1 + v2 verification)

A **handoff** is the formal end of one agent's work session on a task. It
captures what was done, what remains, and what the next agent needs to know.

## When to Write a Handoff
- Whenever you change `status` to `review`, `blocked`, or `done`.
- Whenever you end a work session, even mid-task (handoff to yourself).
- Whenever you escalate to a human or another agent.

## File Naming
```
handoffs/<task-id>__<from-agent>__to__<to-agent>.md
```
If multiple handoffs occur on the same task between the same agents, append
a timestamp:
```
handoffs/T-0007__codex__to__claude__2026-05-22T1105.md
```

## Required Sections (Markdown)
```markdown
# Handoff: T-0007
**From:** codex
**To:** claude
**Date:** 2026-05-22T11:05:02Z
**Task Status After Handoff:** review

## What I Did
- Created tasks/active/, tasks/done/, tasks/blocked/ directories.
- Wrote tasks/active/EXAMPLE.yaml as a reference template.
- Updated PHASE_1_TASKS.md with task entries.

## What Remains
- Schema review for edge cases (multi-owner tasks, retries).
- Confirm `depends_on` semantics — block vs. warn?

## Decisions Made
- Used YAML over JSON for task files (human-editable).
  See ADR-0002.

## Open Questions
- Should `blocked` tasks auto-notify the human, or only on next agent read?

## How to Verify My Work
1. Run `ls tasks/active/` — expect EXAMPLE.yaml.
2. Parse EXAMPLE.yaml with any YAML loader — must succeed.
3. Check PHASE_1_TASKS.md links resolve.

## Risks / Caveats
- None identified. risk_level remained `low` throughout.

## Recommended Next Action for Receiver
Review EXAMPLE.yaml against TASK_SCHEMA.md. If acceptable, mark task `done`
and move to tasks/done/. Otherwise, return with comments via a new handoff.
```

## Handoff Protocol v2 — Repository Verification (mandatory for new handoffs)

Handoffs created **after 2026-06-20** for review-closeout or recovery milestones must include:

```markdown
**Handoff Protocol:** v2
```

and a `## Repository Verification` block with these fields (real values, not placeholders):

```markdown
## Repository Verification

repo_root: <git rev-parse --show-toplevel>
branch: <exact branch name>
base_sha: <40-char canonical milestone base>
implementation_sha: <40-char commit containing code/test/validator changes>
tests_commit_sha: <must equal implementation_sha>
final_head_sha: <40-char branch tip at handoff time — do not self-embed in same commit>
remote_head_sha: <must equal final_head_sha after push>
git_status_clean: <true|false — list tracked exceptions if false>
validator_commit_sha: <commit where validator last passed with suite>
test_count: <discovered unittest count>
test_exit_code: <0 required for closeout>
validator_exit_code: <0 required for closeout>
post_test_diff_policy: docs-only-allowlist-v2
post_test_files: <comma-separated paths changed after tests_commit_sha, or none>
working_copy_path: <absolute canonical clone path>
```

**Enforceable invariants (not self-referential):**

1. `tests_commit_sha` must equal `implementation_sha`.
2. `tests_commit_sha` must be an ancestor of `final_head_sha` (Git check via `scripts/verify_repository_verification.py`).
3. `remote_head_sha` must equal `final_head_sha` at handoff time (Git check when HEAD is supplied).
4. `test_exit_code` and `validator_exit_code` must be `0`.
5. Commits after `tests_commit_sha` may touch only the post-test allowlist:
   `docs/**`, `handoffs/**`, `tasks/**`, `runtime/unittest_last_run.txt`.
6. Any change under `dispatch/`, `scripts/`, `tests/`, `schemas/`, `protocol/`, `agents/`, `daemon/`, `dashboard/`, `orchestrator/`, or `integrations/` after `tests_commit_sha` invalidates verification and requires a new full test run.

`scripts/validate.py` performs offline structural checks. `scripts/verify_repository_verification.py` performs Git-backed checks (ancestor, post-test diff, HEAD equality). Status values: `verified`, `structurally_valid`, `git_verification_required`, `failed`.

When self-reference prevents embedding `final_head_sha` literally inside the commit that creates the handoff, use `final_head_ref: branch HEAD` in prose and record `artifact_parent_sha` as the tested implementation commit; run `git rev-parse HEAD` after push for authoritative SHAs.

**Future:** Git notes or CI attestations can attach test results to a final commit without changing that commit's tree hash. Not implemented in Phase 3.3.2.

Historical v1 handoffs (without `**Handoff Protocol:** v2`) remain valid and are not retroactively required to add this block. `scripts/validate.py` enforces v2 fields only when the v2 marker is present.

## Rules
1. **The outgoing agent writes the handoff.** Never the incoming one.
2. A handoff is **immutable** once committed. Corrections go in a new handoff.
3. Every handoff must be referenced by a `handoff` event in
   `logs/agent-events.jsonl`.
4. If the receiver is `human`, the handoff must also be linked from the PR
   description.
5. Empty or boilerplate handoffs are protocol violations.
