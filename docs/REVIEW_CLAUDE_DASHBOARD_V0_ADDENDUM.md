# Addendum to REVIEW_CLAUDE_DASHBOARD_V0.md — Corrections

- Date: 2026-05-23
- Author: claude
- Triggered by: Codex's PR #1 inspection (verified against `main`'s `docs/TASK_SCHEMA.md`)

This is a correction to `docs/REVIEW_CLAUDE_DASHBOARD_V0.md`. The original
review stands in repo history; this addendum supersedes the inaccurate
sections.

## Retracted: B3 (schema mismatch)

The original review claimed Gemini's parser was reading fields that "do not
exist in the real schema." That claim was wrong. The live `docs/TASK_SCHEMA.md`
at `main` uses exactly the keys the parser reads: `created`, `updated`,
`acceptance_criteria`, `handoff_notes`, `priority: P0..P3`,
`estimated_effort`, `labels`, `blocks`, `related_decisions`.

Gemini was correct against the schema as written. The architect (Claude) had
drifted toward a schema v2 that existed only in drafted-but-unsigned
documents. **B3 is fully retracted.**

## Narrowed: B6 (event log field names)

The original review asserted the events parser used the wrong keys. This
should not be asserted until verified against a recent
`logs/agent-events.jsonl` from `main`. If the live log uses `event`/`task`,
the parser is correct; if it uses `type`/`task_id`, the parser is wrong.

ADR-0004 (event vocabulary, proposed) intends to standardize on `type` going
forward, with a migration window. B6 is **narrowed**: the parser may be
correct today and require an update after ADR-0004 is accepted and the log
is migrated.

## Still standing (unchanged from the original review)

- **B1.** Read-only scope violation. The Control Room tab makes the dashboard a second writer to the protocol surface. Remove for V0.
- **B2.** Calls `scripts/create_handoff.py`, which does not exist. The repo has `scripts/new_handoff.py`. This codepath hard-fails at runtime.
- **B4.** Self-approval. `T-DASHBOARD-V0.yaml` was written with `owner: claude`, low risk, no human approval, despite touching `dashboard/`, `tests/`, `docs/`, and adding deps. Per ADR-0003, this is medium + human approval.
- **B5.** Non-conformant task ID (`T-DASHBOARD-V0` vs `T-NNNN`).
- **B7.** HTML injection surface. Interpolated values inside `unsafe_allow_html=True` blocks must pass through `html.escape()`.

## Net effect on T-0013

T-0013 still supersedes T-DASHBOARD-V0, but for different reasons than the
original review claimed. The corrected scope of T-0013 is:

1. Drop the Control Room tab (B1).
2. Fix the broken script reference (B2).
3. Use a conformant task ID and ADR-0003-compliant approval posture (B4, B5).
4. HTML-escape all interpolated values (B7).
5. Track event log parser correctness against ADR-0004's outcome (B6).
6. **Once ADR-0005 is accepted and T-0015 lands, switch the parser to v2 field names** — but the work in PR #1 against v1 is not wasted; the v1 readers stay compatible during the migration window.

## Sequencing update

1. Sign **ADR-0005** (task schema v2).
2. Sign **ADR-0004** (event vocabulary).
3. Sign **ADR-0003** (already accepted; verify in repo).
4. Land **T-0015** (schema migration).
5. Land **T-0012a** (CLI guardrails + T-0012 rollback) against v2.
6. Land **T-0013** (read-only dashboard, schema-aligned to v2).
7. Open **T-0014** (read-write dashboard, future) behind its own ADR.

## Recommendation on PR #1

Close PR #1 without merge. The dashboard read-side code in Gemini's branch
is salvageable and should be picked up cleanly in T-0013 after T-0015. The
task file `T-DASHBOARD-V0.yaml` is superseded by `T-0013.yaml`. Add a
closing comment on PR #1 pointing to ADR-0005 + T-0015 + the corrected
T-0013.

## Apology and lesson

The architect (Claude) should have verified the live schema before writing
B3. The lesson is the same one ADR-0003 already captured for protocol
violations: **read the repo before asserting what the repo contains**.
Codex's catch is exactly the kind of cross-check the reviewer/implementer
split is designed to produce. Recording it here so it is not lost.

## Sign-off

- [x] claude (author of addendum)
- [x] human (acknowledgement) - Gabriel Achim approved following Claude direction on 2026-05-23
