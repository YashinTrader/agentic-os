# Antigravity — Phase 1.7 kickoff

You are Antigravity, working solo on the Agentic OS repo. Phase 1 is closed.
Phase 1.7 is dashboard hardening + UX polish, in two tasks: T-0017 then T-0018.

## Branch / PR strategy

- One branch per task: `antigravity/T-0017-guardrail-parity` and later
  `antigravity/T-0018-dashboard-polish`.
- Do NOT start T-0018 until T-0017 is merged. They both touch `dashboard/app.py`.

## Before you open any PR — mandatory self-review gate

This is new policy as of ADR-0006. Read it carefully.

1. Open the task YAML.
2. Diff your implementation against `non_goals` line by line. If any
   non-goal is touched, STOP. Do not open the PR. Open an ADR amendment to
   the task FIRST in a separate `chore:` PR, get it signed, then implement.
3. Diff your implementation against `acceptance` line by line. Every bullet
   must be satisfied or explicitly waived in the PR description with a
   reviewer-addressed justification.
4. Run `python scripts/validate.py`. Must exit 0.
5. Run the full test suite. Must be green.
6. Only then open the PR.

Verbal scope changes from the human are NOT scope changes until the task YAML
is amended. If the human asks you mid-task to add a feature, your response is:
"Got it — I'll open a chore PR to amend the task YAML first, then implement."

## T-0017 first

Read `tasks/active/T-0017.yaml` and `decisions/ADR-0006-dashboard-is-read-write.md`
in full. T-0017 is `risk_level: high` and `requires_human_approval: true`. Do
NOT start coding until ADR-0006 is signed by the human and by Claude. Confirm
sign-off by checking the ADR file in `main`.

Strong recommendation in T-0017.notes: shell out to `scripts/` helpers from
the dashboard rather than extracting a shared module. Less surface area, less
risk. If you choose option (b), the extraction must land cleanly in the same
PR with no behavior change to the CLI.

## T-0018 second

Pure read-side UX. Stdlib-only. Server-rendered HTML + vanilla JS. Ship
something polished — this is where your strengths play.

## Handoff

When each task is done, write
`handoffs/T-00XX__antigravity__to__human.md` per HANDOFF_PROTOCOL.md.
