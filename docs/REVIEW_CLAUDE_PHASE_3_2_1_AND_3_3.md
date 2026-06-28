# Claude Final Review — Phase 3.2.1 + Phase 3.3

- **Reviewer:** claude (architect/final reviewer)
- **Date:** 2026-06-20
- **Branch:** `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN`
- **Local HEAD:** `b7a1239b4e429dd6c903433c6ed773ab71a03c95`
- **Remote HEAD:** `b7a1239b4e429dd6c903433c6ed773ab71a03c95` (matches local)
- **Base:** `557914624b4288ff3250ff31cf4f0455f8209119` (canonical Phase 3.2 MVP — confirmed merge-base)

## Verdict

**APPROVE WITH CHANGES**

The code is correct and safe. All four Phase 3.2.1 hardening items are implemented properly, the Phase 3.3 design is thorough and genuinely design-only, the execution boundary is intact, and I independently reproduced 280 passing tests + a clean validator. The branch is built on the canonical Phase 3.2 base with correctly renumbered ADRs (0020–0024) — the integrity incident was recovered cleanly.

The "changes" are real but none are execution-safety holes. They cluster in three areas: (1) the committed test artifact references the wrong commit and was generated from the deprecated Codex clone; (2) two of the four hardening items (M2, L3) have no regression tests despite this project's consistent discipline of testing every safety fix; (3) several supporting documents still carry stale, inaccurate claims — the same claims-vs-reality drift that caused the original incident. Given the incident history, document and artifact accuracy is now a trust-critical property, not a nicety.

I am **not** flipping the ADR-0020–0024 reviewer sign-off boxes, because the prompt conditions that on the branch passing **all** integrity/test/validator/safety checks, and the committed `runtime/unittest_last_run.txt` referencing an older commit from the wrong clone is — by the prompt's own definition — a required integrity fix. Flip the boxes once the required fixes land.

---

## Repository Integrity

**PASS (with one artifact-hygiene exception, see below).**

| Check | Result |
|---|---|
| Branch exists locally | ✅ `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN` |
| Branch exists on `origin` | ✅ `git ls-remote` → `b7a1239…` |
| Local HEAD == Remote HEAD | ✅ both `b7a1239b4e429dd6c903433c6ed773ab71a03c95` |
| Based on canonical Phase 3.2 (`5579146`) | ✅ `git merge-base HEAD 5579146` == `5579146` (ancestor) |
| Expected pre-follow-up HEAD `02cd934` is ancestor | ✅ `02cd934` → `b7a1239` is the verification-only follow-up commit |
| Claimed milestone files tracked (not merely untracked) | ✅ all 7 spot-checked files return from `git ls-files` |
| ADR numbers do not collide | ✅ 0020–0024 are next unused; 0014–0019 unchanged (empty diff) |
| Phase 3.2 tests not removed | ✅ 280 ≥ 262 baseline (+18) |
| `git status` clean of milestone artifacts | ✅ only untracked items are my own prior review docs + stray scratch files (see below) |

**Commit chain (canonical):**
```
5579146  T-PHASE3-2 controlled executor MVP        (canonical base)
  └ 579c2b0  feat: recover Phase 3.2.1 + 3.3 on Phase 3.2 base   (substantive)
      └ 02cd934  docs: fix recovery handoff validator sections
          └ b7a1239  chore: refresh verification artifact        (HEAD, docs-only)
```

**Untracked working-tree files (NOT part of the branch):** my prior-turn review docs `docs/REVIEW_CLAUDE_PHASE_3_0_1.md`, `_3_1.md`, `_3_2.md`, plus a pile of stray scratch outputs at repo root (`test_out.txt`, `test_output.txt`) and under `runtime/` (`test_*.txt`, `unittest_*.txt`, `live_test_output.txt`, etc.). These are not committed and are not milestone artifacts, but they are clutter that should be cleaned or gitignored so future reviewers don't mistake them for deliverables.

---

## Independent Test and Validator Results

- **Independent full run:** `py -m unittest discover -s tests -p "test_*.py"` → **Ran 280 tests in 377.975s — OK**
- **Regenerated via `py scripts/run_tests.py` at HEAD on the canonical clone:** exit 0, `runtime/unittest_last_run.txt` → `commit: b7a1239`, `exit_code: 0`
- **Validator:** `py scripts/validate.py` → **Validation passed** (only documented historical v1 `event`-field warnings on `logs/agent-events.jsonl` lines 1–13)
- **Test count:** 280 ≥ 262 Phase 3.2 baseline. The recovery handoff's "280" is accurate; the **self-review's "220 tests" is stale** (Codex-clone number).

**Artifact integrity exception (required fix):** the *committed* `runtime/unittest_last_run.txt` at HEAD records:
```
commit: 02cd934                                          ← HEAD's PARENT, not HEAD
python: C:\Users\gabot\Documents\Codex\agentic-os\.venv-win\Scripts\python.exe   ← the deprecated Codex clone
```
Per the review instruction ("if `unittest_last_run.txt` still references an older commit, treat that as a required integrity fix"), this is a required fix. It also reintroduces, in a committed file, a reference to the exact clone (`C:\Users\gabot\Documents\Codex\agentic-os`) that the incident report says to stop using. I verified the code is green at the true HEAD by regenerating from the canonical clone (`C:\Users\gabot\agentic-os`), but the committed artifact should not be trusted as-is.

---

## Phase 3.2.1 Hardening Review

### M1 Path Containment — IMPLEMENTED CORRECTLY ✅

- `dispatch/path_containment.py:path_is_inside()` uses `Path.resolve(strict=False)` + `relative_to()`. **No `str.startswith`.** This is the exact fix for the Phase 3.2 M1 finding.
- Sibling-prefix attack blocked: `relative_to` raises `ValueError` for `/safe-evil` vs `/safe`. Covered by `test_sibling_prefix_blocked`.
- Traversal (`..`) blocked twice — `relative_to` plus an explicit `".." in relative.parts` guard.
- Absolute-outside blocked; Windows drive mismatch blocked (`resolved.drive.lower() != root.drive.lower()`).
- Symlink-escape detection via `_symlink_escapes_root` (walks symlink hops, blocks loops and out-of-root targets).
- **Wiring verified:** `dispatch/worktree_policy.py` `_resolve_inside` and `path_inside_any_root` both now delegate to `path_is_inside` (diff confirmed the `startswith` line was replaced).
- **Tests:** `tests/test_path_containment.py` (5 cases) + existing `tests/test_dispatch_worktree_policy.py` (4 cases). Good coverage.

### M2 Preview Freshness — IMPLEMENTED CORRECTLY, TEST GAP ⚠️

- `dispatch/execution_gate.py` now converts a freshness-verification exception into a **blocking** reason on the execute path:
  ```python
  except Exception as exc:
      msg = f"preview freshness cannot be verified: {exc}"
      if operator_execute and not dry_run:
          blocked.append(msg)      # --execute → blocks
      else:
          warnings.append(msg)     # --dry-run → warns
  ```
- This is the correct fix for the Phase 3.2 M2 finding: a missing/malformed plan (where `load_plan`/`load_task_for_plan` raises) now **blocks** `--execute`, so `execute_dispatch` returns before `subprocess.run`. The stale-plan case (`is_preview_stale`) blocks on both paths.
- **Gap 1 (Medium):** on `--dry-run`, an unverifiable plan is only a warning, so the dry-run result still reports `execution_allowed: true`. The review criteria asked for dry-run to report `execution_allowed: false` when freshness cannot be verified. The safety property holds (the binding check is at `--execute`), but the dry-run signal is misleadingly permissive — an operator could see "dry-run OK" then hit a block at execute. Recommend dry-run also report `execution_allowed: false` (or a distinct `freshness_unverified` status) for honest parity.
- **Gap 2 (High):** there is **no regression test** for M2. No test exercises `--execute` with a missing/malformed plan to prove the block. The existing executor tests were only updated to *seed* a valid `latest_state.json` so they keep passing — they do not test the failure path. A future refactor could silently demote this back to a warning.

### L1 supports_execution — IMPLEMENTED CORRECTLY ✅

- `scripts/validate.py`: `supports_execution` added to `ADAPTER_REQUIRED_FIELDS` plus an explicit check — `None` → "missing required field", non-`bool` → "must be a boolean".
- `agents/adapter_registry.yaml`: all 6 adapters now declare `supports_execution` explicitly. Only `local-python-exec-test` is `true`; composer/codex/claude/cursor/blocked-mcp are all `false`.
- Runtime default safely false: `execution_gate.adapter_supports_execution` returns `bool(adapter.get("supports_execution"))` → missing/false → False.
- `supports_execution: true` alone cannot bypass other gates — it only adds a requirement on the `--execute` path; allowlist, CLI inventory, freshness, approval, worktree, secrets, and MCP gates all still apply.
- **Tests:** `tests/test_phase3_2_1_hardening.py` — canonical registry passes, missing field fails, string `"true"` rejected. Solid.

### L3 Event Error Observability — IMPLEMENTED CORRECTLY, TEST GAP ⚠️

- The Phase 3.2 bare `except Exception: pass` in `_emit_dispatch_event` is **gone**. On emit failure it now: (a) appends a structured message to an `event_emit_errors` list, and (b) writes an `event_emit_error` line to the per-run `events.jsonl`. A nested failure is itself captured, not raised.
- `ExecutionResult` gained an `event_emit_errors: list[str] = field(default_factory=list)` field, so `asdict(result)` serializes it into `result.json`. The executor sets `result.event_emit_errors` and re-writes `result.json` on every return path (blocked, dry-run, executed).
- No silent swallow; no recursion (the local recorder is `append_run_event`, a different function whose own failure is caught); primary execution result remains deterministic (emit failures don't change `executed`/`exit_code`).
- The `event_emit_error` per-run type is correctly **not** added to the canonical `ALLOWED_EVENT_TYPES` (it goes to the run-local `events.jsonl`, not `logs/agent-events.jsonl`).
- **Gap (High):** there is **no test** referencing `event_emit_errors`. The composer self-review explicitly claims "Mocked central emit failure still produces successful fixture execution with non-empty `event_emit_errors` persisted in `result.json`" — that test does not exist in the branch (`grep -rn event_emit_errors tests/` → no matches). This is a false claim in the self-review, and the safety-observability property is untested.

---

## Phase 3.3 Design Review

Design quality is high. All five docs are genuinely design-only (no operational modules), honest about limitations, and cover every required dimension. Schemas are clean JSON Schema draft 2020-12 with `additionalProperties: false`.

### Worktree Allocation (ADR-0020 / WORKTREE_ALLOCATOR_DESIGN)
- One run owns one worktree under `runtime/dispatch/worktrees/<run_id>/`; no sharing across concurrent runs.
- Sanitized branch names (`alphanumeric / - only`, max 120 chars; schema enforces `maxLength: 120`).
- `base_commit` recorded; `dirty_before`/`dirty_after` flags; cleanup states (`preserve_on_failure` / `clean_on_success` / `manual`).
- Safe deletion boundary: worktree path must pass `path_is_inside()`; cleanup never deletes outside the allocated root; destructive cleanup needs operator approval under ambiguity.
- No direct main mutation, no auto-merge. Explicit non-goal: no `git worktree add` implementation in 3.3.

### Approval Authenticity (ADR-0021 / APPROVAL_AUTHENTICITY_DESIGN)
- Binds preview_hash + plan_hash + command_hash + cwd_hash + scope_hash + adapter_id; adds `nonce` for anti-replay; `issued_at`/`expires_at`; `revoked_at`.
- Replay to another run/task/adapter blocked via nonce + binding fields; changed command/cwd/scope invalidates; system approvals can never satisfy `human`.
- No secrets in repo; recommended MVP = HMAC-SHA256 with key from OS keyring at Phase 3.4 (options table compares 5 approaches). Honest that current Phase 3.2 records are forgeable/replayable.

### Scheduling Boundaries (ADR-0022 / SCHEDULING_BOUNDARIES)
- Autonomy levels 0–4 defined; **current runtime MUST remain Level 1** stated explicitly and enforced (only operator `--execute`).
- Prohibits: auto task pickup, recurring dispatch, background agent launch, silent retry loops, paid-model auto-escalation, auto-approval of human gates, auto-merge/push, external user-facing actions.
- Future scheduler requirements enumerated: concurrency caps, per-agent locks, cancellation API, dead-letter, operator pause, global emergency stop. Future `scheduler/` package explicitly forbidden from calling subprocess or invoking `execute_dispatch` without operator flag.

### Adapter Promotion (ADR-0023 / AGENT_ADAPTER_PROMOTION)
- 16-item checklist (adapter-specific ADR, allowlist, forbidden args, CLI inventory, timeout, cwd/scope, writes_files+rollback, worktree, network, secrets metadata, MCP=false for CLI, dry-run tests, isolated-worktree integration tests, rollback procedure, reviewer sign-off, human sign-off for high-risk).
- Promotion states `planned → preview_only → test_execution → restricted_execution → active → (disabled | revoked)`.
- `schemas/adapter_promotion.schema.json` enforces `adr_ref` pattern `^ADR-[0-9]{4}`. Registry posture table confirms all real adapters remain `false`. No dashboard toggle.

### Runtime Governance (ADR-0024 / RUNTIME_GOVERNANCE)
- Concurrency caps (global 2, per-agent 1, one file-writing run per repo), per-agent locks, resource budgets, cancellation (SIGTERM → 10s grace → SIGKILL), orphan/stale-run detection.
- Session lifecycle: completion is **not** exit-code alone — requires handoff file, verification results, changed-file inventory.
- Monitoring honesty: subscription/token data may be unobservable; design supports exact API metering when available, CLI-log estimates otherwise, `unknown` when neither — no provider scraping in 3.3.

---

## Execution Boundary Review

**CLEAN.** Verified by callsite grep (not just imports):

| Surface | Result |
|---|---|
| Runtime `subprocess.run` callsites | `dispatch/executor.py:274` (approved) + pre-existing `daemon/cli_discovery.py` (version probes), `scripts/run_tests.py`, `dashboard/app.py:455` (CLI script runner — task file mutations, reviewed Phase 3.0). No new dispatch execution surface. |
| Dispatch preview executes? | No — `dispatch/preview.py` has no `subprocess`. |
| Dashboard execute/approve/launch/schedule/promote/allocate/run-mcp | None. Forms found are pre-existing `/comment`, `/update_task`, `/create_task`, filters. |
| Orchestrator executes dispatch? | No — `grep` of `orchestrator/` for executor import/`execute_dispatch` → none. |
| Daemon autonomously executes dispatch? | No — only `cli_discovery` version probes. |
| `scheduler/` implementation | Absent. |
| Worktree allocator implementation | Absent (design doc only). |
| Approval signing / HMAC implementation | Absent. |
| MCP execution | `blocked-mcp-preview` is `status: disabled` + `supports_execution: false`. |
| Real-agent adapter execution | All `supports_execution: false`. |
| Fixture | `local-python-exec-test` → `python -c "print('agentic-os-executor-test')"`, no writes/network/secrets, 30s timeout, `approval_level: none`, fully gated. |

---

## ADR and Protocol Review

- **ADR-0020–0024 are the actual next unused numbers.** ADR files on disk are exactly 0001–0024, one per number.
- **ADR-0014–0019 unchanged** in this branch (empty diff) — prior decisions preserved.
- `decisions/INDEX.md` lists 0001–0024 with no duplicates and no gaps introduced by this milestone (the blank line between 0006/0007 is a pre-existing cosmetic artifact from earlier phases).
- Approval levels appropriate: all five new ADRs are design records marked "accepted (design only), pending claude review" with no human-approval requirement — correct for routine design ADRs.
- **Reviewer sign-off not pre-flipped by composer** — correct; they left "pending claude review" for me to complete.
- `protocol/event_types.py` **unchanged** since Phase 3.2 — no premature Phase 3.3 event types emitted. The Phase 3.2 execution events were already in `ALLOWED_EVENT_TYPES` from `5579146`; this branch adds none.

---

## Recovery Incident Review

**The incident response is high quality and honest.**

- **Classification accurate:** "Class A — work existed locally in an alternate clone, never pushed; compounded by an inaccurate handoff." Matches the evidence I independently confirmed last turn (commits `ef39087`/`3a26e1e` were never on `origin`; the branch was absent).
- **Root cause documented:** wrong working copy (`C:\Users\gabot\Documents\Codex\agentic-os`, Phase 3.0 base), no `git push`, handoff claimed remote-verifiable state.
- **"Rebuilt" vs "recovered" terminology accurate:** the doc correctly says *rebuilt on canonical base by porting artifacts*, **not** a cherry-pick of the original commit chain.
- **Canonical Phase 3.2 base preserved:** confirmed `5579146` is the merge-base.
- **Test-count discrepancy resolved:** 220 (stale Codex) → 280 (canonical), independently reproduced.
- **ADR collision corrected:** 0014–0018 → 0020–0024, mapping table provided.
- **Branch pushed; local/remote SHA match:** confirmed.
- **Prevention controls documented:** single canonical clone path, no completion claim without `git push` + `git ls-remote`, ADR allocation from INDEX on the real base, test-count non-regression, full 40-char SHAs in handoffs.

**Endorsement:** I strongly recommend adopting the proposed **mandatory handoff verification block**. Every future completion handoff should embed, copy-pasted from real commands:

```
repo_root:         <git rev-parse --show-toplevel>
branch:            <git branch --show-current>
base_sha:          <git merge-base HEAD <phase-base>>
local_head_sha:    <git rev-parse HEAD>            # full 40 chars
remote_head_sha:   <git ls-remote origin <branch>> # full 40 chars
git_status_clean:  <true|false>
tests_commit_sha:  <commit recorded in unittest_last_run.txt>
test_count:        <Ran N tests>
validator_exit:    <0|n>
```

The single most valuable invariant: **`tests_commit_sha` must equal `local_head_sha`**, and both must be produced from `repo_root` — which is precisely the check that would have caught both this milestone's stale artifact and the original incident.

---

## Critical Issues

None. No execution-safety hole, no real adapter enabled, no autonomous execution, no premature implementation of worktree/scheduler/signing/MCP. Design-only is respected.

## High-Priority Issues

- **H1 — M2 has no regression test.** No test proves `--execute` blocks when the plan is missing/malformed (freshness unverifiable). The code is correct today; without a test, a refactor can silently demote the block back to a warning on a safety-critical path.
- **H2 — L3 has no regression test, and the self-review falsely claims one exists.** `grep -rn event_emit_errors tests/` returns nothing, yet `REVIEW_COMPOSER_PHASE_3_2_1_AND_3_3_SELF_REVIEW.md` asserts a mocked-emit-failure test persists `event_emit_errors` to `result.json`. The observability fix is real but untested.

## Medium-Priority Issues

- **M-1 — Committed `runtime/unittest_last_run.txt` references the wrong commit (`02cd934`, HEAD's parent) and the deprecated Codex clone python path.** Required integrity fix per the review brief. Regenerate from the canonical clone at HEAD, or gitignore the artifact and replace it with the handoff verification block convention above.
- **M-2 — M2 dry-run reports `execution_allowed: true` on an unverifiable plan.** Honesty/UX gap (not a safety hole). Dry-run should report `execution_allowed: false` or a distinct `freshness_unverified` status so the dry-run signal matches what `--execute` will actually do.
- **M-3 — Documentation inaccuracies (trust-critical given the incident).** `docs/PHASE_3_2_1_HARDENING_REPORT.md` lists `dispatch/approval.py` (does not exist) and `dispatch/freshness.py` as *added* files (freshness.py was not modified in this branch). `REVIEW_COMPOSER_PHASE_3_2_1_AND_3_3_SELF_REVIEW.md` still says "five ADRs (0014–0018)" and "220 tests / commit `12350d5`" — stale Codex-clone numbers never updated after the rebuild. `handoffs/T-PHASE3-3-DESIGN__...md` says "ADR-0020–0018" (typo). These are the same claims-vs-reality class that caused the incident.

## Low-Priority Issues

- **L-1 — Working-tree clutter.** Stray scratch files at repo root (`test_out.txt`, `test_output.txt`) and under `runtime/` (`test_*.txt`, `unittest_*.txt`, `live_test_output.txt`). Clean or extend `.gitignore`.
- **L-2 — Phase 3.3 schemas are not wired into `scripts/validate.py`.** Acceptable for design-only, but note that they are unenforced until Phase 3.4 consumes them.
- **L-3 — `unittest_last_run.txt` is tracked on this branch** (it was gitignored before). Decide deliberately: either keep it gitignored (regenerate locally) or treat it as a committed verification record — but if committed, it must reference HEAD from the canonical clone (ties to M-1).

## Required Fixes

Tracked in `tasks/active/T-PHASE3-3-REVIEW-FIXES.yaml`:

1. **(M-1)** Regenerate / correct `runtime/unittest_last_run.txt` so it references the reviewed HEAD from the canonical clone (`C:\Users\gabot\agentic-os`), or gitignore it and adopt the handoff verification block. **Required before approval per review brief.**
2. **(H1)** Add an M2 regression test: `--execute` with a missing and with a malformed plan must yield `execution_allowed: false` with a "preview freshness cannot be verified" block reason and must not reach `subprocess.run`.
3. **(H2)** Add an L3 regression test: with `protocol.emit_event.append_event` mocked to raise, fixture execution still completes and `result.json` contains a non-empty `event_emit_errors` (make the self-review's claim true).
4. **(M-3)** Correct the documentation: hardening report file list (remove `dispatch/approval.py`, fix the freshness.py/added claim), self-review (ADR 0014–0018 → 0020–0024, 220 → 280, commit reference), and the design-handoff "ADR-0020–0018" typo.

Recommended (not blocking): **(M-2)** dry-run freshness parity; **(L-1)** clean scratch files.

These are documentation, test-coverage, and artifact-hygiene fixes. None require changing the hardening logic, which I verified is correct.

## Phase Readiness

**READY FOR PHASE 3.4 DESIGN ONLY**

The Phase 3.3 design itself is approve-quality and ready to inform Phase 3.4. But Phase 3.4 (worktree allocator + HMAC approval signing) is the most dangerous implementation step yet, and it must not begin until: (a) the M2/L3 hardening paths have regression tests, (b) the committed verification artifact is trustworthy, and (c) the documentation accuracy is restored. Being conservative, I gate Phase 3.4 *implementation* behind the required fixes; Phase 3.4 *design* refinement may proceed against the accepted ADRs now.

## Recommended Next Milestone

**Phase 3.3.1 — Review-fix closeout (M-1, H1, H2, M-3), then Phase 3.4 design lock.**

Single next milestone: land the four required fixes above and re-run `scripts/run_tests.py` from the canonical clone with a verification block in the handoff. Only after that closeout should **Phase 3.4 — Worktree Allocator + Approval Authenticity MVP** begin, and it must still keep:

- all real-agent adapters disabled (`supports_execution: false`);
- no autonomous scheduling (Autonomy Level 1);
- operator-commanded execution only (`execute_dispatch.py --execute`).

Do **not** promote any real-agent adapter or implement a scheduler as part of 3.4.

## Final Reviewer Notes

This milestone recovered well from a serious integrity incident, and the substance is genuinely good: M1 fixes the precise `str.startswith` containment bug I flagged in Phase 3.2, L1 closes the `supports_execution` typo-risk at the validator, and the Phase 3.3 design is the most complete and honest design package the project has produced — particularly the governance doc's candor about unobservable token/quota data.

What holds this back from a clean APPROVE is a recurrence, in miniature, of the very pattern the incident was about: a self-review and hardening report that assert things the repository does not contain (an L3 test that isn't there, a `dispatch/approval.py` that doesn't exist, "220 tests / ADR 0014–0018" that predate the rebuild), and a committed test artifact that points at the wrong commit and the deprecated clone. The code is safe; the paperwork is not yet trustworthy. For a project whose entire safety model rests on file-based, auditable claims, that distinction matters — so the fixes are required, not optional.

Fix the four required items, adopt the mandatory handoff verification block, and this is a clean APPROVE and a green light for the Phase 3.4 MVP. I am holding the ADR-0020–0024 reviewer sign-offs until the integrity-artifact and test-coverage fixes land.

---

### Reported facts

1. **Reviewed branch:** `agent/composer/T-PHASE3-2-1-AND-3-3-DESIGN`
2. **Local HEAD:** `b7a1239b4e429dd6c903433c6ed773ab71a03c95`
3. **Remote HEAD:** `b7a1239b4e429dd6c903433c6ed773ab71a03c95` (matches local)
4. **Test count / exit code:** 280 tests, exit 0 (independently reproduced; validator-passing)
5. **Validator:** passed (historical v1 warnings only)
6. **Verdict:** APPROVE WITH CHANGES
7. **Required fixes:** unittest_last_run.txt commit/clone correction (M-1); M2 regression test (H1); L3 regression test (H2); documentation accuracy (M-3)
8. **Phase readiness:** READY FOR PHASE 3.4 DESIGN ONLY
9. **Recommended next milestone:** Phase 3.3.1 review-fix closeout, then Phase 3.4 Worktree Allocator + Approval Authenticity MVP (real adapters disabled, Level 1, operator-commanded only)
