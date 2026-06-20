# Handoff: Repository Integrity Recovery — Phase 3.2.1 + 3.3 Design

**From:** composer (recovery agent)  
**To:** claude (reviewer)  
**Date:** 2026-06-20

## What Happened

A prior handoff claimed Phase 3.2.1 + Phase 3.3 design was complete on branch `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN` with commits `ef39087`, `468bf99`, `3a26e1e`. Independent verification found:

- Branch and commits absent from `origin`
- Work isolated in `C:\Users\gabot\Documents\Codex\agentic-os` on a **Phase 3.0 base**, not Phase 3.2 `5579146`
- ADR numbering collision (0014–0018 already used for Phase 3.1/3.2)
- Test count regression claim (220 vs 262)

## Root Cause

Wrong working copy + no `git push` + handoff stated remote-verifiable artifacts that were local-only.

## What Was Recovered or Rebuilt

**Rebuilt** on canonical Phase 3.2 base `5579146` by porting real artifacts from the Codex clone:

- Phase 3.2.1 hardening: `dispatch/path_containment.py`, pathlib-safe worktree policy, M2 execute-time freshness block, L1 `supports_execution` validator requirement, L3 `event_emit_errors`
- Phase 3.3 design-only docs, schemas, tasks, ADR-0020–0024
- Tests: `test_phase3_2_1_hardening.py`, `test_phase3_3_design.py`, `test_path_containment.py`; executor test fixture fix for orchestrator state

This is **not** a replay of commits `ef39087`/`468bf99`/`3a26e1e`; those remain local-only in the Codex clone.

## Repository Path Used

`C:\Users\gabot\agentic-os`

## Branch and Commit Verification

See post-push section below — run verification commands after reading this handoff.

## Remote Verification

After push, confirm:

```powershell
git ls-remote --heads origin agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN
```

Local and remote HEAD must match (full 40-char SHA).

## Tests and Validator

- **280 tests**, `exit_code: 0` (see `runtime/unittest_last_run.txt` after final commit)
- `python scripts/validate.py` → **Validation passed**

## ADR Number Corrections

| Incorrect (Codex handoff) | Correct (canonical tree) |
|---------------------------|--------------------------|
| ADR-0014 worktree allocation | ADR-0020 |
| ADR-0015 approval authenticity | ADR-0021 |
| ADR-0016 no autonomous execution | ADR-0022 |
| ADR-0017 adapter promotion | ADR-0023 |
| ADR-0018 concurrency limits | ADR-0024 |

Phase 3.1/3.2 ADR-0014–0019 unchanged.

## Remaining Risks

- Codex clone @ `3a26e1e` still exists locally with stale/conflicting ADR numbers — do not merge without discarding.
- `runtime/unittest_last_run.txt` is gitignored; verify on checkout.
- M2 freshness block on `--execute` when orchestrator `plan_path` points to non-JSON `plan.md` — intentional safety behavior.

## How Claude Can Independently Verify

```powershell
cd C:\Users\gabot\agentic-os
git fetch origin
git checkout agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN
git rev-parse HEAD
git ls-remote --heads origin agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN
git ls-files dispatch/path_containment.py
git ls-files docs/PHASE_3_3_DESIGN_SPEC.md
git ls-files docs/PHASE_3_3_REVIEW_PACKET.md
git ls-files handoffs/T-PHASE3-3-DESIGN__composer__to__claude.md
git status --short
python scripts/run_tests.py
python scripts/validate.py
git log -5 --oneline --decorate
git diff origin/main...HEAD --stat
```

## Recommended Next Action

Review Phase 3.3 design docs and ADR-0020–0024 on the pushed branch. Do **not** proceed to Phase 3.4 implementation until Claude signs off Phase 3.3 design packet.