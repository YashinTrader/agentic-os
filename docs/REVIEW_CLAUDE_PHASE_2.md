# Claude Review — End of Phase 2

- **Reviewer:** claude (architect/reviewer)
- **Date:** 2026-06-07
- **Scope:** Phases 2.0 – 2.5
- **Branch:** `agent/composer/T-PHASE2-HARDENING-001-review-packet`
- **Verification commands run:** `py -m unittest` → **155 passed**, `py scripts/validate.py` → **Validation passed** (only documented v1 log warnings)

---

## Verdict

**APPROVE WITH CHANGES**

Phase 2 is internally consistent, safe under its stated planning-only scope,
and the validator + tests give credible coverage of the critical boundaries
(output-dir sandbox, graph short-circuit, registry cross-refs, review-packet
sections). The new ADRs 0010 – 0012 and the Phase 3 readiness criteria correctly
define the dispatch boundary.

The "changes" are not blockers for merging Phase 2.5, but they must be fixed
before any Phase 3 execution work begins. They cluster around two themes:

1. **Risk gate correctness** — the keyword-ordering and `requires_human_approval`
   handling in `orchestrator/risk.py` can downgrade dangerous tasks to "none".
   It is advisory in Phase 2, but it is what Phase 3 will read first.
2. **Event-vocabulary drift between docs and emitters** — `protocol/event_types.py`
   defines `discovery_completed`, `vault_sync_planned`, `vault_sync_completed`,
   etc., but no emitter actually uses them: the daemon writes `type: "note"` and
   the Obsidian sync writes nothing at all. The canonical vocabulary should be
   the source of truth for emitters, not just for the validator.

Both are documented below as **High Priority** for Phase 2.6 (review-fix
milestone) and **must** land before Phase 3 dispatch is unlocked.

---

## Executive Summary

Phase 2 is coherent and ready as a Phase 3 foundation **for design only**, not
for implementation.

- The local-first, file-as-bus architecture is preserved across 2.0 – 2.4.
- The orchestrator is genuinely planning-only: no LLM, no MCP, no agent
  execution, no task mutation, `executed_automatically: false` is hard-coded
  in `generate_plan_dict()`, and the dashboard provides no execution surface
  for the orchestrator, daemon, or Obsidian sync.
- Path-traversal containment is implemented in three places (orchestrator
  output-dir, task path, Obsidian vault-relative paths) and each has tests.
- The graph error short-circuit works as described: invalid/missing tasks
  flow through `persist_failure`, `latest_plan.json` is removed, and
  `next_action: fix_task_input` is set.
- Registries (skills, MCPs, teams, roles) cross-validate, and planned MCPs
  are constrained to `command: null` / `endpoint: null` by the validator.
- ADR-0012 + `PHASE_3_READINESS_CRITERIA.md` correctly enumerate the gates
  that must be implemented before any dispatch work.

The repo can merge Phase 2.5 after the required fixes below; Phase 3
implementation must remain blocked.

---

## Architecture Review

**Consistent with the local-first, file-based control plane.**

- `daemon/`, `orchestrator/`, `integrations/obsidian/`, and the registries all
  write under `runtime/`, `tasks/`, `logs/`, `handoffs/`, `decisions/`, or
  `memory/`. Nothing writes to a database, a network endpoint, or a path
  outside the repo by default.
- `runtime/` is the canonical machine-readable surface; `runtime/orchestrator/`,
  `runtime/registry/`, and `runtime/status/` follow a uniform pattern.
- The orchestrator graph (`orchestrator/graph.py`) is the largest new
  abstraction in Phase 2, but it composes deterministically over the existing
  registries and loaders. No hidden state, no side channels.
- `scripts/` remains the single ingress for CLI operations; all dashboard
  mutations shell out to those same scripts (`append_log.py`, `update_task.py`,
  `create_task.py`), preserving one authoritative write path.
- The Streamlit dashboard is read-only for daemon, orchestrator, registries,
  and Obsidian sync — confirmed by grep: no callsite invokes
  `orchestrate_task.py`, `sync_obsidian.py`, or `daemon.daemon`.

**Minor architectural inconsistencies (Medium):**

- `orchestrator/nodes.py:124` inserts `<repo>/scripts` into `sys.path` at
  runtime so it can import `suggest_team`. This works but breaks the package
  boundary; `scripts/suggest_team.py` should either expose `score_team` /
  `load_teams_registry` as a library module under `orchestrator/` (or a
  shared `lib/`), or `nodes.py` should import via a stable path.
- `daemon/registry_writer.append_discovery_event()` writes `type: "note"`
  even though `discovery_completed` exists in the canonical vocabulary.
  Same issue applies to the Obsidian sync, which emits no log event at all.

---

## Protocol Review

**Task schema, handoffs, ADRs, and event vocabulary are coherent.**

- Task schema v2 (`docs/TASK_SCHEMA.md` + `scripts/validate.py`) is enforced
  consistently. Mixed v1/v2 rename pairs are rejected. `reviewer` ≠ `owner`
  and `human_approval_checklist` non-empty when `requires_human_approval`
  are both enforced. The migration window is well-documented and idempotent
  (covered by `tests/test_schema_v2_migration.py`).
- Handoff format checks (`# Handoff: ...`, four required metadata markers,
  seven required sections) are enforced. The Phase 2.5 handoff
  `T-PHASE2-HARDENING-001__composer__to__claude.md` complies.
- ADR template + INDEX format are followed. ADR-0010 / 0011 / 0012 each pass
  the validator's section requirements and are listed in `INDEX.md`.
- `protocol/event_types.py` centralizes Phase 1 + Phase 2 vocabularies and is
  the single source consulted by `scripts/validate.py` and
  `scripts/append_log.py`.

**Notable issue (High):** Phase 2 event types are **declared but unused**.
- `discovery_completed` — never emitted; `daemon/registry_writer.py` uses `type: "note"`.
- `vault_sync_planned` / `vault_sync_completed` — never emitted;
  `scripts/sync_obsidian.py` does not append any event.
- `registry_updated` — never emitted; registry edits land via PR only.
- `validation_passed` / `review_packet_created` — defined but no caller writes them.

This is a soft drift: the validator accepts them, the protocol documents them,
but no observable run actually produces them. Either the emitters must adopt
the canonical types or the canonical set should be pruned. Until Phase 3
dispatch reads these events, this is non-blocking; for Phase 3 dispatch
auditing it is a hard requirement.

**Minor (Low):** ADR-0011 is referenced by the index as "Phase 3" related but
the index/grouping has a stray blank line between ADR-0006 and ADR-0007.
Cosmetic.

---

## Safety Review

**Strong on the documented boundaries; one over-broad doc claim and one risk-gate logic bug.**

**Confirmed safe:**

- `scripts/orchestrate_task.py:resolve_output_dir()` rejects (a) `..` segments
  and (b) absolute paths outside the repo unless `--allow-outside-repo` is set
  explicitly. Three tests cover the matrix. No callsite passes
  `--allow-outside-repo` from the dashboard or any other automation.
- `orchestrator/loaders.py:resolve_task_path()` rejects paths outside the
  repo and outside `tasks/`. Mode `must_exist=False` is correctly used only
  inside the graph (so `persist_failure` can record the error), while
  `scripts/orchestrate_task.py:main` always calls `safe_task_path` (with
  `must_exist=True`) first.
- `integrations/obsidian/vault_writer.py:safe_join()` resolves and
  `.relative_to(root)` checks every write. `mapping.py:resolve_vault_path()`
  rejects `..` segments, expands `~`, and validates the directory exists.
- Daemon discovery uses `shutil.which` + `subprocess.run(..., shell=False,
  timeout=5)`. Failure modes (timeout, missing CLI, non-zero exit) are
  swallowed without crashing. No network, no shell, no secrets.
- MCP registry validator enforces `command: null` / `endpoint: null` for
  `status: planned` entries; all three currently-defined MCPs are
  `planned`/`human` approval; no execution code path exists.
- Dashboard write surfaces are limited to `append_log.py`,
  `update_task.py`, `create_task.py` — there is no "Run agent",
  "Trigger sync", or "Run orchestration" button anywhere in `dashboard/app.py`.

**Risk-gate correctness bug (High):** `orchestrator/risk.py:evaluate_risk()`
walks the keyword sets in this order:

1. `READ_ONLY_KEYWORDS` — short-circuits to `approval_level: none`.
2. `HUMAN_KEYWORDS` — sets `human`.
3. `requires_human_approval` flag / `risk_level: high` — but only triggers
   `human` if a secondary regex matches.
4. `REVIEWER_KEYWORDS` — sets `reviewer`.

Two real failure modes:

- A task with text such as "Dry-run plan for production deploy" hits
  `"dry-run"` first and is classified as `none`, even though "production"
  and "deploy" are explicit human-approval triggers.
- A task with `requires_human_approval: true` whose text does not match
  the second-stage regex (`\b(deploy|secret|merge|production|destructive|database)\b`)
  is silently downgraded to `reviewer` (or even `none` if a read-only keyword
  matches). The explicit flag is supposed to be an authoritative contract;
  the risk gate must not override it.

The correct ordering is:
1. `requires_human_approval: true` → always `human` (no keyword required).
2. `HUMAN_KEYWORDS` → `human`.
3. `REVIEWER_KEYWORDS` or `risk_level in {medium, high}` → `reviewer`.
4. `READ_ONLY_KEYWORDS` *only* if none of the above matched → `none`.

Phase 2 risk-gate is "advisory only", but Phase 3 dispatch will read this
value first. Fix is small and well-tested in isolation.

**Doc-vs-code claim (Medium):** `docs/OBSIDIAN_SYNC.md` section "Safety Rules"
states: "Only overwrite files under `AgenticOS/` that this sync owns." In
practice, `vault_writer.py:write_note()` performs `target.write_text(...)`
unconditionally as long as the path resolves under the configured root —
there is no manifest of "owned" files and no check that a target file was
previously written by this sync. The blast radius is limited to the user's
configured `<vault>/AgenticOS/` folder, but the doc claim should be softened
to match reality, or the sync should record/check an owned-files manifest in
`.sync/`. Recommend the former for now.

---

## Validation and Test Review

**Validator coverage is appropriate for Phase 2. Tests pass on a fresh
checkout (155/155).**

- `scripts/validate.py` covers tasks (v1 & v2), handoffs, ADRs, all four
  registries with cross-refs, Obsidian mapping schema, and the Phase 2 review
  docs/ADR section markers. Generated/runtime artifacts
  (`runtime/`, `latest_*.json`) are correctly *not* required.
- The event-log validator now **errors** on an unknown `type` value but only
  **warns** on the deprecated `event` field — exactly the behavior described
  in ADR-0004 and the migration map. Historical v1 lines do not block CI.
- `tests/test_phase2_hardening.py` provides 11 tests covering the post-2.5
  guarantees (output sandbox, missing/invalid tasks, error-state dashboard
  loader, vocabulary enforcement, review-packet sections, ADR sections,
  append_log accepting new types). This is the right surface to defend.
- `tests/test_orchestrator_graph.py` exercises load → classify → suggest
  → end-to-end against a *copy* of the real repo. Brittle to repo layout
  changes but correctly placed in a temp dir.
- `tests/test_schema_v2_migration.py` covers idempotent migration plus
  three validator rejection paths.

**Issues:**

- **Medium:** The risk-gate test suite (`tests/test_risk_gate.py`) does not
  cover the precedence failure described above. Specifically, it does not
  test:
  - `requires_human_approval: true` with no risky text.
  - A task containing both a read-only and a human-approval keyword.
  - A `risk_level: high` task whose text does not match the secondary regex.
  Adding these would have caught the issue.
- **Low:** `tests/test_orchestrator_graph.py` copies the entire repo into a
  tempdir for each test. Acceptable, but the suite takes ~260 s on Windows;
  consider a class-level fixture for Phase 3.
- **Low:** The orchestrator graph imports `from suggest_team import ...`
  via `sys.path.insert(0, repo/scripts)`. If the test runner inherits a
  `suggest_team` from a different location (highly unlikely but possible
  on a developer machine with stale `PYTHONPATH`), tests could pick up the
  wrong module. Use a package-relative import.

---

## Orchestrator Review

**Planning-only is correctly enforced.** Concretely:

- `orchestrator/planner.py:generate_plan_dict()` hard-codes
  `executed_automatically: False` and `statement: "This plan is advisory only.
  No agents were launched."` — both written into the JSON plan and the
  Markdown plan.
- No node calls any agent SDK, OpenAI/Anthropic/Gemini client, MCP
  transport, or HTTP library.
- No node mutates the task YAML. `task_data` is read into memory and never
  written back.
- `finalize` only writes `state.json`, `latest_state.json`, `latest_plan.json`,
  and appends a single `orchestration_planned` event. Skipped on `dry_run`
  or `no_log`, skipped on errors.

**Short-circuit:** `graph._route_after_load` correctly routes to
`persist_failure` on any `errors`. `_wrap()` makes every downstream node a
no-op if `state.errors` is non-empty (so even if the conditional edge were
mis-configured in a refactor, the downstream nodes would still be safe).
`persist_failure` clears `latest_plan.json`. Verified by
`test_missing_task_does_not_generate_plan` and
`test_invalid_yaml_does_not_generate_plan`.

**Context packs** are reasonable and safe. They include task summary,
team/agent/skill/MCP metadata, recent handoffs (preview only), and recent
log events — all from the local filesystem. Files-to-inspect is derived
purely from declared `inputs`/`outputs` in the task. No code execution,
no fetches.

**`latest_state` / `latest_plan` behavior** is acceptable: on success both
are overwritten with the latest run; on failure `latest_state` is overwritten
with the error state and `latest_plan` is removed. The dashboard tab gracefully
handles both states (`test_dashboard_loader_handles_orchestrator_error_state`).

**Concerns:**

- **High:** Risk gate (see Safety Review).
- **Low:** `compile_context_markdown` reads the first 500 chars of each
  handoff and embeds it in the context pack. Fine, but if a handoff
  contains accidentally-pasted secrets, those would propagate to vault
  sync. The Obsidian sync already excludes `.env`/`*.key`, but it does not
  scan content. Worth a future content-level filter (Phase 3 hardening).
- **Low:** `team_suggestion` falls back to `recommended_primary_agent =
  "composer"` if the team has no `builder` and no members — fine for now,
  but worth documenting that this is a default, not a guarantee.

---

## Governance Review

**Approval model matches ADR-0012 and PHASE_3_READINESS_CRITERIA.md.**

- Routine work (registry browse, task list, validator runs) requires no
  approval.
- Reviewer approval covers protocol changes, validator changes, registry
  edits, and adapter additions. Phase 2.5 ADRs themselves were correctly
  marked `approval_level: reviewer`.
- Human approval is reserved for secrets, paid APIs, external side
  effects, CI/deploy triggers, prod DB, destructive filesystem ops, merging
  to `main`, and security-model changes. All eight categories are
  enumerated in `PHASE_3_READINESS_CRITERIA.md` §B.

**Phase 3 dispatch gates** in ADR-0012 are clear and tied to a concrete
implementation checklist. The asymmetry between "documented" and
"implemented" gates is explicit in
`PHASE_3_READINESS_CRITERIA.md` §A (only E1 and E7 are ✅; E2 – E6 are ⏳).

**Concerns:**

- **Medium:** The approval model is documented in three places
  (`AGENT_PROTOCOL.md` §5, ADR-0012, `PHASE_3_READINESS_CRITERIA.md` §B)
  with slightly different lists. They are not contradictory, but a single
  source of truth (e.g., move the canonical list to
  `PHASE_3_READINESS_CRITERIA.md` and have the others link to it) will be
  necessary once Phase 3 starts enforcing them in code.
- **Low:** ADR-0010 / 0011 / 0012 sign-off blocks have an empty checkbox
  for claude reviewer. This review fills that slot; please flip the
  checkboxes when merging.

---

## Critical Issues

None. No issue blocks merging Phase 2.5.

---

## High Priority Issues

These **must** be fixed before any Phase 3 dispatch work begins. They do
not block merging the current branch, but they should land in a Phase 2.6
"review-fix" milestone.

### H1. Risk-gate keyword ordering and ignored `requires_human_approval` flag

- **Where:** `orchestrator/risk.py:evaluate_risk()`
- **What:** `READ_ONLY_KEYWORDS` is checked before `HUMAN_KEYWORDS`, and
  `requires_human_approval: true` only escalates to `human` if a secondary
  regex matches.
- **Why it matters:** Phase 3 dispatch will read `approval_level` first.
  Tasks like "Dry-run plan for production deploy" or
  `requires_human_approval: true` without obvious deploy/secret keywords
  can be silently downgraded.
- **Fix:** Reorder to (1) explicit flag → human, (2) human keywords → human,
  (3) reviewer keywords / risk_level → reviewer, (4) read-only keywords
  only if no other matched. Add `tests/test_risk_gate.py` cases for each
  of the three failure modes above.

### H2. Event-vocabulary drift: declared types are never emitted

- **Where:**
  - `daemon/registry_writer.py:append_discovery_event()` emits
    `type: "note"` instead of `discovery_completed`.
  - `scripts/sync_obsidian.py` emits no event at all; `vault_sync_planned`
    / `vault_sync_completed` exist in the canonical vocabulary but have
    no emitter.
  - `registry_updated`, `validation_passed`, `review_packet_created` have
    no emitters.
- **Why it matters:** Phase 3 dispatch auditing requires events to be
  emitted by the actual subsystem doing the work. Defining the words but
  never speaking them defeats the audit story.
- **Fix:** Either (a) wire each emitter to the canonical type, or
  (b) prune the canonical set to only what is actually emitted. Option
  (a) is preferred — adopt `discovery_completed` in the daemon and emit
  `vault_sync_planned` / `vault_sync_completed` from `scripts/sync_obsidian.py`.

---

## Medium Priority Issues

### M1. Risk-gate tests do not cover precedence failures

`tests/test_risk_gate.py` has four tests, none of which exercise the
failure modes in H1. Add three tests targeting that ordering.

### M2. `OBSIDIAN_SYNC.md` claims "only overwrite files this sync owns"

Code does not check ownership; only the AgenticOS/ root containment is
enforced. Either soften the doc or implement an owned-files manifest
(`.sync/owned_files.json`). Recommend softening the doc for Phase 2 and
deferring ownership tracking to Phase 3.

### M3. Cross-package import via `sys.path` insertion

`orchestrator/nodes.py:124` adds `<repo>/scripts` to `sys.path` to import
`suggest_team`. Expose `score_team`/`load_teams_registry` as importable
library functions (e.g., `orchestrator/team_scoring.py` or `lib/teams.py`)
and have both the script and the orchestrator import from there.

### M4. Approval-model lists duplicated in three docs

`AGENT_PROTOCOL.md` §5, `ADR-0012` "Approval" row, and
`PHASE_3_READINESS_CRITERIA.md` §B all enumerate human-approval triggers
with minor variations. Pick one canonical location and link from the
others before Phase 3 starts enforcing them.

### M5. `daemon_status.json` and `cli_inventory.yaml` are committed in
"empty" / "uninitialized" state

These are runtime artifacts. They should be in `.gitignore` (with a
sentinel `.gitkeep` or a `README.md` in the parent directory) or
explicitly committed with realistic placeholder content. Committing
literal `mode: "uninitialized"` is confusing to a fresh checkout.

---

## Low Priority Issues

- **L1.** Three historical lines in `logs/agent-events.jsonl` use unknown
  v1 events (`task_started`, `task_completed`, `handoff_created`). Validator
  only warns; the open question in the handoff asks whether to migrate.
  Recommend a one-off migration via `scripts/migrate_schema_v2.py`-style
  rewriter, mapping these to `status_changed`/`handoff_written` as
  appropriate. Optional cleanup.
- **L2.** `decisions/INDEX.md` has a stray blank line between ADR-0006 and
  ADR-0007.
- **L3.** ADR-0010 / 0011 / 0012 sign-off `claude` checkbox is empty.
  Flip when merging.
- **L4.** `dashboard/app.py:407` calls `subprocess.run(...)` without
  `shell=False` explicitly. It is the default, but explicit is safer once
  any of the args become user-controllable (currently they are not).
- **L5.** `tests/test_orchestrator_graph.py` copies the entire repo per
  test; ~260 s wall time is acceptable but a class-level fixture would
  reduce CI cost.
- **L6.** Context pack embeds the first 500 chars of each handoff;
  consider a content scrubber for known secret patterns before Phase 3.

---

## Required Fixes

Tracked in `tasks/active/T-CLAUDE-PHASE2-FIXES.yaml`.

Summary of in-task work for composer/codex:

1. **H1 (risk gate):** rewrite `evaluate_risk` precedence and add tests.
2. **H2 (event vocabulary):** wire `discovery_completed` in the daemon
   and `vault_sync_planned` / `vault_sync_completed` in
   `scripts/sync_obsidian.py`; or prune unused canonical types.
3. **M1:** new `tests/test_risk_gate.py` cases for the three precedence
   failure modes.
4. **M2:** soften `OBSIDIAN_SYNC.md` "Safety Rules" §3.
5. **M3:** extract `score_team`/`load_teams_registry` into an importable
   module and remove the `sys.path` insertion in `orchestrator/nodes.py`.
6. **M4:** consolidate the human-approval list into one canonical doc and
   link from the others.
7. **M5:** decide whether to gitignore the empty runtime artifacts or
   commit a meaningful placeholder.
8. **L1 – L6:** cleanup items, optional, can be deferred.

None of these block merging Phase 2.5.

---

## Recommended ADR Updates

- **ADR-0004 / ADR-0010:** add a Consequences note that emitter parity
  with `protocol/event_types.py` is required; the validator alone is not
  sufficient evidence that the vocabulary is in use.
- **ADR-0011:** add a Consequences note that the risk-gate keyword
  precedence is the contract Phase 3 dispatch will read; the current
  ordering is a known bug and must be fixed before any dispatch ships
  (reference H1 above).
- **New ADR-0013 (recommended):** "Canonical approval-model source of
  truth" — pick one document and make the others reference it. Small ADR,
  reviewer approval.

No existing ADR is wrong as written; these are clarifications.

---

## Phase 3 Readiness

**READY FOR PHASE 3 DESIGN ONLY**

Justification:

- `PHASE_3_READINESS_CRITERIA.md` correctly marks E1 and E7 as ✅ and
  E2 – E6 as ⏳; this matches reality.
- No agent adapter, dry-run runner, allowlist, command preview, timeout
  wrapper, log-capture harness, approval-enforcement layer, or worktree
  isolation strategy exists in code yet.
- The risk gate (H1) cannot yet be trusted as a Phase 3 input.
- The event-vocabulary drift (H2) means Phase 3 dispatch audit trails
  would be partial today.

A Phase 3 *design spec* (interfaces, contracts, ADRs for dispatch adapter,
approval enforcement, sandbox/worktree, log capture) is appropriate now.
Phase 3 *implementation* must remain blocked until H1, H2, and at least
E2/E3/E5/E6 from the readiness criteria are implemented with tests.

---

## Recommended Next Milestone

**Phase 2.6 — Claude Review Fixes + Phase 3 Design Spec**

Bundle the H1, H2, M1 – M5 fixes with the Phase 3 design ADRs (dispatch
adapter contract, allowlist, dry-run/preview, timeout/log capture,
worktree isolation, approval enforcement). Output is design + fixes; no
new execution code.

Do **not** start Phase 3 implementation in this milestone. Phase 2.6
should land as a single review-mergeable branch reviewed by claude
again before any Phase 3 implementation task is opened.

---

## Final Reviewer Notes

The Phase 2.5 hardening work is high quality: well-scoped, well-tested,
and the documentation packet (`PHASE_2_REVIEW_PACKET.md`,
`PHASE_2_HARDENING_REPORT.md`, `PHASE_3_READINESS_CRITERIA.md`) makes
this review tractable. ADR-0012 is a particularly good guardrail — it
gives reviewers a concrete checklist to refuse premature execution work
against.

The two High-priority issues (risk-gate precedence, event-vocabulary
drift) are the kind of latent bugs that only matter once a planner becomes
a dispatcher. Catching them now, while the system is still planning-only,
is exactly what an end-of-phase review is for. Neither requires a redesign.

Phase 2 is approved for merge once the two `claude` reviewer checkboxes
in ADR-0010 / 0011 / 0012 (and ADR-0010 deferred sign-off) are flipped
and this review document is committed. Phase 3 stays blocked.
