# Repository Integrity Incident — Phase 3.2.1 + Phase 3.3 Design

**Date:** 2026-06-20  
**Reporter:** Composer (recovery agent)  
**Classification:** **A** — work existed locally in an alternate clone and was never pushed to `origin`; compounded by an inaccurate handoff that claimed remote-verifiable state.

## Evidence

### Claimed vs actual (Claude verification)

| Claim | Actual |
|-------|--------|
| Branch `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN` on `origin` | **Absent** — `git ls-remote --heads origin` returned no match |
| Commits `ef39087`, `468bf99`, `3a26e1e` | Exist **only** in `C:\Users\gabot\Documents\Codex\agentic-os` (local); not on `origin` |
| Base commit `5579146` in same working copy | `5579146` exists in `C:\Users\gabot\agentic-os`, **not** in Codex clone |
| 220 tests | Phase 3.2 canonical clone had **262** tests at `5579146`; Codex clone reported 220 on a different base |
| ADR-0014–0018 for Phase 3.3 | **Collision** — ADR-0014–0019 already used for Phase 3.1/3.2 in canonical clone |

### Working copies discovered

1. **`C:\Users\gabot\Documents\Codex\agentic-os`** — branch `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN` @ `3a26e1e0de0b7e861dcfb428e4bbd5836ef067ad`, based on Phase 3.0 followup (`12350d5`), never pushed.
2. **`C:\Users\gabot\agentic-os`** — branch `agent/composer/T-PHASE3-2-CONTROLLED-EXECUTOR` @ `557914624b4288ff3250ff31cf4f0455f8209119` (Phase 3.2 MVP), never pushed for this branch either.

### `origin/main` at investigation time

`5589bda3d3bee208273c57f268455f1fbc293bf7` — no Phase 3.2 merge, no Phase 3.3 design artifacts.

## Root cause

1. Composer session used the **Codex workspace clone** (Phase 3.0 base) instead of the **canonical Phase 3.2 clone** at `C:\Users\gabot\agentic-os`.
2. Completed work was **never pushed** to `origin`.
3. Handoff reported completion as if branch/commits/files were remotely verifiable and based on `5579146`.
4. Phase 3.3 ADRs were numbered **0014–0018**, colliding with existing Phase 3.1/3.2 ADRs in the canonical tree.

## Affected claims

- Remote branch existence
- Commit hashes as review targets on GitHub
- Test count monotonicity (220 < 262)
- ADR numbering for Phase 3.3
- `runtime/unittest_last_run.txt` commit alignment

## Recovery status

**Rebuilt on canonical base** (not a straight cherry-pick of `ef39087`/`468bf99`/`3a26e1e`):

- Base: `557914624b4288ff3250ff31cf4f0455f8209119` (Phase 3.2 controlled executor MVP)
- Ported Phase 3.2.1 hardening and Phase 3.3 design artifacts from Codex clone
- Renumbered Phase 3.3 ADRs to **ADR-0020–ADR-0024**
- Preserved Phase 3.2 test suite; added 18 tests (280 total)
- Branch `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN` created, committed, pushed to `origin`

## Prevention actions

1. **Single canonical clone path** documented in handoffs (`C:\Users\gabot\agentic-os` for Phase 3.2+).
2. **No completion claim without** `git push` + `git ls-remote` verification.
3. **ADR numbers** must be allocated from `decisions/INDEX.md` on the actual base branch before writing ADRs.
4. **Test count** must not decrease vs prior phase without documented suite restructure.
5. Handoffs must include full 40-character HEAD SHA and remote SHA after push.