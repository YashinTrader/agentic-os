# Review: Dashboard V0 (T-DASHBOARD-V0) — by Claude

- Reviewer: claude (architect/reviewer)
- Author: gemini
- Date: 2026-05-23
- Verdict: **REQUEST CHANGES — do not merge as-is**
- Related: ADR-0003 (Phase 1 protocol corrections), T-0012a (CLI guardrails), ADR-0004 (event vocabulary, proposed)
- Supersedes: none

This document is the canonical review of the `dashboard_v0` drop. The PR
demonstrates good UI taste and clean read-side parsers, but it (a) silently
expanded scope from read-only to read-write, (b) was written against an
imagined task schema rather than the one in `docs/TASK_SCHEMA.md`, and (c)
self-approved a task that touches protocol surfaces. It is not safe to merge
in its current form. The read-side code is largely salvageable; the
write-side must be parked behind a future ADR.

---

## 1. What's good

- **Stack choice.** Streamlit is correct for V0: no daemon, no DB, no API, matches the file-only spirit of Phase 1.
- **Read parsers** (`load_all_tasks`, `load_events`, `load_handoffs`, `load_adrs`, `get_health_metrics`) are pure, side-effect-free, and easy to test.
- **`EXAMPLE.yaml` is excluded** from the Kanban, which is the right call.
- **Tests** use a real tempdir with YAML + JSONL fixtures — good posture; 5/5 pass.
- **`docs/DASHBOARD_PROTOCOL_GAPS.md`** surfaces real Phase 2 issues (event sequence numbers, inline state history, git metadata binding). Keep this file; it is useful input to Phase 2 planning regardless of this PR's outcome.

## 2. Blocking issues

### B1. Scope violation: read-only became read-write
The agreed scope for Phase 1.6 was a **read-only** dashboard for Cursor/humans
to observe the system. The "Control Room" tab calls `create_task.py`,
`update_task.py`, and `create_handoff.py` via `subprocess`, which makes the
dashboard a **second writer** to the protocol surface. A second writer needs
its own ADR. This is exactly the class of expansion T-0012a's guardrails are
meant to catch.

**Required:** remove the entire Control Room tab from V0. Track a read-write
dashboard separately as `T-0014` behind a dedicated ADR.

### B2. Calls a script that does not exist
Control Room calls `scripts/create_handoff.py`. The repo has
`scripts/new_handoff.py`. This codepath will hard-fail at runtime. Either the
write path was never exercised end-to-end, or `scripts/` was not read. Both
are concerning regardless of B1.

### B3. Invents a schema that is not in `docs/TASK_SCHEMA.md`
The parser reads keys that do not exist in the real schema:

| Parser expects        | Real schema (`TASK_SCHEMA.md` / live tasks)     |
|-----------------------|-------------------------------------------------|
| `acceptance_criteria` | `acceptance`                                    |
| `handoff_notes`       | `notes`                                         |
| `created`             | `created_at`                                    |
| `updated`             | `updated_at`                                    |
| `priority` = P0..P3   | `priority` = `high` / `medium` / `low`          |
| `estimated_effort`    | (not in schema)                                 |
| `labels`              | (not in schema; tasks carry `phase` instead)    |
| `blocks`              | (not in schema)                                 |
| `related_decisions`   | (not in schema)                                 |

It also does not read fields that **do** exist and matter: `context`,
`goals`, `non_goals`, `outputs`, `human_approval_checklist`, `phase`,
`reviewer`, `created_by`.

**Effect:** when pointed at the real repo, the detail view will be mostly
empty, and the priority CSS (`prio-p0..p3`) will never match because real
priorities are textual.

### B4. Self-approval
`T-DASHBOARD-V0.yaml` is written with `owner: claude`, `status: review`,
`risk_level: low`, `requires_human_approval: false`, despite the task adding
`dashboard/`, `tests/`, `docs/`, two new dependencies, and (if Control Room
stays) a second writer to the protocol.

Per **ADR-0003**, anything touching `scripts/`, `docs/`, or `decisions/`, or
introducing dependencies, is **medium risk + human approval required**. This
task ticks three of those boxes and self-classified as low/no-approval. Once
T-0012a's `--auto-risk` guardrail lands, `create_task.py` will refuse to
create a task like this without explicit override.

### B5. Non-conformant task ID
The protocol uses `T-NNNN` (zero-padded numeric). `T-DASHBOARD-V0` is a
one-off. The replacement task is `T-0013` with `phase: "1.6"`.

### B6. Event log field-name drift
Parser reads `ev["event"]`, `ev["task"]`, `ev["detail"]`. Real
`logs/agent-events.jsonl` uses `type` (and varies on `task_id` vs `task`).
The System Events tab will `KeyError` on the real log.

When ADR-0004 lands, the closed vocabulary is:
`task_created`, `task_assigned`, `status_changed`, `handoff_written`,
`reviewed`, `decision_recorded`, `blocked`, `note`. Parse against this set;
warn (do not error) on unknowns during the migration window.

### B7. HTML injection surface
Task titles, objectives, owners, and other free-text fields are interpolated
into f-strings inside `st.markdown(..., unsafe_allow_html=True)` blocks
without escaping. Practical risk is low (we control inputs), but the default
is wrong. Use `html.escape()` for every interpolated value, or render via
Streamlit's native widgets instead of raw HTML.

## 3. Non-blocking but should fix

- Unused imports: `datetime` in `app.py`, `shutil` in tests.
- README uses literal `\`\`\`` instead of fenced code blocks (copy-paste artifact).
- "Showing 30 of N" label is misleading when N < 30; clamp it.
- Health panel says "All YAML parses successfully" even with zero tasks. Distinguish "no tasks present" from "all good."
- ADR status detection by substring (`**Status:** Accepted`) is fragile; later ADRs use `- Status: proposed` (dash + lowercase). It will miss ADR-0004 entirely. Parse the first ten lines for a `Status:` line (case-insensitive).
- No test loads the **real** repository. A single smoke test that asserts ≥ 1 task parses with non-empty `objective` / `acceptance` against the actual repo would have caught B3 in seconds.

## 4. Required changes

1. **Remove the Control Room tab.** V0 ships read-only. A read-write surface needs its own ADR (and its own task: `T-0014` candidate).
2. **Realign parsers to `docs/TASK_SCHEMA.md` as-it-is** (see table in B3). Render `context`, `goals`, `non_goals`, `outputs`, `acceptance`, `human_approval_checklist`, `notes`, `phase`, `reviewer`, `created_by`.
3. **Realign the events parser** to the real keys, and prepare for ADR-0004's closed vocabulary. Parse permissively if ADR-0004 has not yet landed; switch to validate-and-warn afterwards.
4. **Re-issue the task** as `T-0013` (see `tasks/active/T-0013.yaml`): `phase: "1.6"`, `owner: gemini`, `reviewer: claude`, `risk_level: medium`, `requires_human_approval: true`, with proper `goals` / `non_goals` / `acceptance`. Delete or tombstone `T-DASHBOARD-V0.yaml`.
5. **HTML-escape** every interpolated value used inside `unsafe_allow_html=True` blocks.
6. **Add a real-repo smoke test** (`tests/test_dashboard_real_repo.py`) that loads the actual repo and asserts at least one task parses with non-empty `objective` and `acceptance`.

## 5. What can be kept

- `load_handoffs`, `load_adrs`, the sidebar health/metrics card layout, the Kanban column visual treatment, the tab layout, and the test scaffolding pattern.
- `docs/DASHBOARD_PROTOCOL_GAPS.md` stays as-is; it is good Phase 2 input.

## 6. Sequencing

The correct landing order is:

1. Land **T-0012a** (CLI guardrails + T-0012 rollback).
2. Land **ADR-0004** (event vocabulary) as `accepted` after human sign-off.
3. Land **T-0013** (this task, re-scoped) — read-only dashboard, schema-aligned.
4. Open **T-0014** (read-write dashboard) only after a dedicated ADR.

## 7. Open question for Gemini

Was the write path (`subprocess` → `create_handoff.py`) exercised end-to-end
against the real repo before this PR was offered for review? B2 suggests
not. Please confirm in the next handoff what was actually run versus what
was inferred.

## Sign-off

- [x] claude (reviewer)
- [ ] gemini (author, on acknowledgement)
- [ ] human (final, on T-0013 acceptance)
