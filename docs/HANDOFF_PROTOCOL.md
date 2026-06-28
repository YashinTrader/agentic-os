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
local_head_sha: <40-char git rev-parse HEAD>
remote_head_sha: <40-char git ls-remote after push>
git_status_clean: <true|false — list tracked exceptions if false>
tests_commit_sha: <40-char commit tested by scripts/run_tests.py>
test_count: <discovered unittest count>
test_exit_code: <0 required for closeout>
validator_exit_code: <0 required for closeout>
validator_commit_sha: <40-char commit validated>
artifact_commit_sha: <40-char commit containing this handoff>
working_copy_path: <absolute canonical clone path>
```

**Critical invariant:** when `runtime/unittest_last_run.txt` is tracked, its `commit_full` (or `commit`) must equal `tests_commit_sha`. If `local_head_sha` differs from `tests_commit_sha`, later commits must be documentation/verification-only and this must be stated in the handoff.

Historical v1 handoffs (without `**Handoff Protocol:** v2`) remain valid and are not retroactively required to add this block. `scripts/validate.py` enforces v2 fields only when the v2 marker is present.

## Rules
1. **The outgoing agent writes the handoff.** Never the incoming one.
2. A handoff is **immutable** once committed. Corrections go in a new handoff.
3. Every handoff must be referenced by a `handoff` event in
   `logs/agent-events.jsonl`.
4. If the receiver is `human`, the handoff must also be linked from the PR
   description.
5. Empty or boilerplate handoffs are protocol violations.
