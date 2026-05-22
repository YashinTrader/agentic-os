# Claude Review — Phase 1

**Reviewer (agent):** claude
**Date:** 2026-05-23
**Scope:** File-based coordination skeleton only (no Phase 2 scope).
**Repo state reviewed:** post-Codex first implementation pass.

## Verdict
**APPROVE WITH CHANGES** — The skeleton is sound, the protocol is internally
consistent, and the validator passes cleanly (`python scripts/validate.py` →
exit 0). Codex's work meets every Phase 1 acceptance criterion in spirit.
However, several **non-blocking corrections** must be applied before
T-0001..T-0005 are marked `done`, and one **procedural issue** (T-0008 was
delivered without its required ADR) must be retroactively resolved.

Phase 1 **should continue** to T-0006 and T-0010 (Claude ADR/review work).
T-0008 (validator) is *already implemented*; only its ADR remains.
T-0009 (CI) remains correctly deferred behind explicit human approval.

---

## 1. Conformance Check (against Manager-Architect plan)

| # | Check | Result |
|---|-------|--------|
| 1 | Repo follows file-based control-plane design | ✅ Pass |
| 2 | Task schemas clear and valid | ✅ Pass (validator green; all required fields present) |
| 3 | Handoff useful and compliant with HANDOFF_PROTOCOL §"Required Sections" | ✅ Pass |
| 4 | Event log valid JSONL, append-only, schema-compliant | ✅ Pass |
| 5 | ADRs present and correctly named | ⚠️ Partial — see Critical Issue #1 |
| 6 | Validator scope appropriate (not too weak/strict) | ✅ Acceptable — see notes in §5 |
| 7 | Contradictions between docs and implementation | ⚠️ Several minor — see §3 |
| 8 | New agent can onboard from README + docs/ only | ✅ Pass (after fixes in §3) |
| 9 | Risky actions gated by ADR + human approval | ⚠️ Partial — see Critical Issue #1 |
| 10 | T-0001..T-0005 ready to be marked done | ⚠️ Not yet — see §4 |

---

## 2. Critical Issues (must fix before closing T-0001..T-0005)

### C1. T-0008 (validator) was implemented without the ADR the backlog requires
`tasks/PHASE_1_TASKS.md` explicitly states for T-0008:
> *"Risk: medium (introduces a dependency: Python + PyYAML). **Requires ADR**
> for adopting Python as the validator language."*

And `docs/AGENT_PROTOCOL.md` §5 lists *"Installing new top-level dependencies"*
as a **risky action requiring an ADR with `approval: human`**.

Codex shipped `scripts/validate.py` + `requirements.txt` (PyYAML) without an
approved ADR. This is a **protocol violation**, even though the result is good.

**Fix:** Adopt `ADR-0003` (included in this drop-in) which retroactively
documents the Python+PyYAML decision with `approval: human` pending the human
sign-off line. Codex did the right *engineering*; only the *paperwork* was
skipped. We accept the work but record the lesson.

### C2. Backlog statuses in `PHASE_1_TASKS.md` are stale
The backlog table still shows T-0001, T-0002, T-0003 as `review` (correct) but
T-0008 (validator) as `☐ todo` even though the validator is committed and
green. The backlog must reflect ground truth or the file-based control plane
becomes unreliable as a source of state.

**Fix:** Update T-0008 to `review` and add a row for **T-0011 — Adopt
ADR-0003** (this review's corrective task), assigned to `claude` → `human`.

---

## 3. Non-Critical Issues (clean up, but not blocking)

### N1. `docs/ARCHITECTURE.md` repo-layout diagram drifted
The original tree used Unicode box-drawing (`├──`, `└──`); Codex replaced it
with ASCII (`|--`, `\`-). Functionally equivalent, but:
- The `scripts/` entry was correctly *added* (good).
- The tree no longer matches the rendered tree on a standard `tree` command,
  which the T-0001 acceptance criterion (`tree -L 2 matches §3`) literally
  references.

**Fix:** Either restore Unicode box-drawing, or relax the T-0001 acceptance
criterion in the backlog to say *"directory set matches §3"* rather than
exact-string match.

### N2. `EXAMPLE.yaml` has `id: T-0000` which collides with the bootstrap log event
The seeded log line uses `"task":"T-0000"` for the human bootstrap event, and
`EXAMPLE.yaml` also claims `id: T-0000`. Not a validator failure, but
semantically muddled — a future agent might think the example *is* the
bootstrap task.

**Fix:** Rename example to `id: T-EXAMPLE` (and filename to `EXAMPLE.yaml` is
fine), or reserve `T-0000` exclusively for the bootstrap event and renumber.
Lowest-friction option: change `EXAMPLE.yaml` to `id: T-EXAMPLE`.

### N3. `outputs` field in `EXAMPLE.yaml` contains prose, not a path
```
outputs:
  - (this file is itself the output)
```
This passes the validator (lists strings) but violates the *spirit* of the
schema, which expects file paths. A new agent copy-pasting from EXAMPLE will
inherit the bad pattern.

**Fix:** Replace with `- tasks/active/EXAMPLE.yaml`.

### N4. `handoffs/README.md` says naming uses double-underscore, but doesn't link to the canonical rule
Minor; just add a one-line `See docs/HANDOFF_PROTOCOL.md §"File Naming"` to
prevent drift if the protocol evolves.

### N5. `decisions/INDEX.md` is missing the table header convention shown in `docs/DECISIONS.md`
The doc shows three columns plus a "(see file)" link convention; the actual
INDEX is bare. Acceptable for now; flag for T-0006 (claude's ADR seeding work)
to extend.

### N6. Handoff `T-0001__codex__to__claude.md` references work beyond T-0001 alone
The handoff bundles T-0001, T-0002, T-0003, and T-0008 deliverables into a
single handoff filed under T-0001. Technically allowed (one work session, one
handoff), but it means T-0002, T-0003, T-0008 have **no handoff of their own**.

**Fix (light-touch):** Either (a) accept the bundled handoff and explicitly
note in the T-0002 / T-0003 / T-0008 task YAMLs that they were handed off as
part of T-0001's handoff (add a `related_handoff:` field, or a line in
`handoff_notes`), or (b) split into per-task handoffs. Recommendation: (a) for
Phase 1 to avoid busywork.

---

## 4. Required Fixes for Codex (next session)

Codex should perform these as **task T-0011** before T-0001..T-0003 are moved
to `tasks/done/`:

1. **Adopt `ADR-0003-phase-1-protocol-corrections.md`** (provided). Append it
   to `decisions/INDEX.md`. Wait for human sign-off line before marking
   accepted.
2. **Update `tasks/PHASE_1_TASKS.md`:**
   - T-0001, T-0002, T-0003 → keep `review` until human merges PR.
   - T-0008 → change `☐ todo` to `review` (it's done in code).
   - Add T-0011 row pointing at this review.
3. **Fix `EXAMPLE.yaml`:** change `id` to `T-EXAMPLE` and `outputs` to a real path.
4. **Fix `docs/ARCHITECTURE.md` §3 tree:** restore Unicode characters OR adjust
   T-0001 acceptance wording. Either is fine; ADR-0003 records the choice.
5. **Add `related_handoff: handoffs/T-0001__codex__to__claude.md`** (or one
   line in `handoff_notes`) to `T-0002.yaml`, `T-0003.yaml`. (T-0008 has no
   task file yet — create a minimal one with `status: review`.)
6. **Re-run validator.** Must remain exit 0.

No code rewrite required. No design changes. ~30 minutes of cleanup.

---

## 5. Validator Assessment

`scripts/validate.py` is **acceptable for Phase 1.** It checks:
- Task YAML required fields, status enum, risk_level enum, list types, bool type.
- Log JSONL parseability and required fields.
- Handoff required sections and metadata markers.
- ADR required sections and metadata markers.

**Strengths:** Lean, no external schema lib, fails fast with clear messages.

**Mild weaknesses (do NOT fix in Phase 1 — log for Phase 2):**
- Does not verify `status` of a task in `tasks/blocked/` is actually `blocked`
  (Codex's own open question N.B. #2 in the handoff).
- Does not check ID uniqueness across `active/`, `done/`, `blocked/`.
- Does not verify `updated` ≥ `created` or that timestamps are ISO-8601.
- Does not check that every `handoff` event in the log has a corresponding
  file in `handoffs/`.
- Does not enforce that ADR filenames match the `# ADR-####:` title inside.

These are *future* enhancements. Phase 1 explicitly says "don't overbuild."

---

## 6. Recommended Next Tasks

Ordered for Codex/Claude to pick up next:

1. **T-0011 — Apply review corrections** (codex, ~30 min). The cleanup list in §4.
2. **T-0006 — Seed decisions/** (claude). ADRs ADR-0001 and ADR-0002 already
   exist; this task can be **closed as already-satisfied** once ADR-0003 is
   added to INDEX. Mark T-0006 `done`.
3. **T-0007 — Handoffs seed** (codex). Already satisfied by the existing
   `handoffs/README.md` + `T-0001__codex__to__claude.md`. Mark `done`.
4. **T-0010 — Claude Phase-1 review** (claude). **This document satisfies it.**
   Mark `done` once ADR-0003 is human-approved.
5. **T-0009 — CI hook.** Remains *correctly* deferred. Do **not** start
   without a fresh ADR (modifying CI config = risky action).

---

## 7. Onboarding Test (per Architecture §10)

I attempted to onboard a hypothetical new agent using only `README.md` + `docs/`:

- ✅ Identity rules clear.
- ✅ Branch-naming clear.
- ✅ Five-step loop (READ→PLAN→ACT→LOG→HANDOFF) clear.
- ✅ Risky-actions list explicit.
- ✅ Event log + handoff + task schemas all have copy-paste examples.
- ⚠️ Onboarding agent would have to **infer** that `EXAMPLE.yaml`'s prose
  `outputs` is wrong (N3) — fix that and onboarding is clean.

Conclusion: After §4 fixes, the file-based skeleton **passes the onboarding
test**.

---

## 8. Verdict Restated

**APPROVE WITH CHANGES.**

- Skeleton is usable today.
- All protocol violations are paperwork-level, not design-level.
- Codex did good engineering; the procedural gap (no ADR for the validator
  dependency) is the single most important lesson.
- After ~30 min of cleanup per §4, Phase 1 is effectively complete and the
  team can pause to consider Phase 2 scope.

— claude
