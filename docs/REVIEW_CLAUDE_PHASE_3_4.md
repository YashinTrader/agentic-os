# Claude Final Review — Phase 3.4 Worktree Allocator + Approval Authenticity MVP

- **Reviewer:** claude (architect/final reviewer)
- **Date:** 2026-06-20
- **Branch:** `agent/composer/T-PHASE3-4-WORKTREE-APPROVAL-MVP`
- **Local HEAD:** `19732d988641eab3c61e8f4e232f282b97813603`
- **Remote HEAD:** `19732d988641eab3c61e8f4e232f282b97813603` (matches local)
- **Base:** `deca7170bd5ee77e04b8a6ec2afe781ebd74cb35` (approved Phase 3.3.2 closeout tip — confirmed ancestor)
- **Implementation/tests commit:** `ecec7669c523ad498dc6697875e3a7d724abe78d`

## Verdict

**APPROVE WITH CHANGES**

This is the most consequential code in the project — the first milestone that actually creates Git worktrees, signs approvals with HMAC, and consumes single-use approval claims — and the engineering is genuinely excellent and safe. I independently reproduced **333 tests OK / exit 0 and validator exit 0 at the actual HEAD `19732d9`** (not merely at the implementation commit), audited every safety-critical module line by line, and confirmed all execution-boundary invariants hold: only the harmless fixture executes, no autonomous allocation, dashboard read-only, no repo secrets, no `shell=True`, subprocess confined to the executor (agent) and the allocator (allowlisted git only).

The "changes" are two **integrity-hygiene** findings — not code-safety issues, and the branch is empirically green so neither is a REJECT:

1. The committed verification artifact `runtime/unittest_last_run.txt` records `commit_full: 0a638bc`, a commit that was **rebased away and is not on the branch** — it disagrees with the handoff block's correct `tests_commit_sha: ecec766`. The recorded run was captured before the rebase and never regenerated.
2. `decisions/` was added to the post-test allowlist in `repository_verification.py`, re-widening the exact gap I flagged last round (ADRs are validated by `validate.py`, so post-test ADR changes can pass verification without the validator being re-run at HEAD).

Because the engineering is approve-quality and I have independently confirmed green-at-HEAD, I approve the implementation. I am **holding the ADR-0025–0028 reviewer sign-offs** until the two integrity fixes land (a small Phase 3.4.1 closeout), consistent with how I gated the 3.2.1+3.3 sign-offs behind the 3.3.2 closeout.

## Repository Integrity

| Check | Result |
|---|---|
| Branch exists locally + on `origin` | ✅ `19732d9…` both |
| Local HEAD == Remote HEAD | ✅ |
| Based on approved tip `deca717` | ✅ ancestor confirmed |
| `tests_commit_sha` (`ecec766`) on branch | ✅ ancestor |
| Post-test diff scope | ⚠️ `decisions/` (5), `docs/` (7), `tasks/` (1), `handoffs/` (1), artifact — **`decisions/` is newly allowlisted** (see F2) |
| `0a638bc` (artifact commit) on branch | ❌ **rebased away, not an ancestor** (see F1) |
| Verify CLI | `Status: verified` (reads the block; did not catch F1) |
| ADR numbering | ✅ 0025–0028 next unused; INDEX clean; 0014–0024 untouched |

## Independent Test and Validator Results

- **Validator at actual HEAD `19732d9`:** exit 0 (historical v1 warnings only).
- **Full suite at actual HEAD `19732d9`:** **Ran 333 tests, OK, exit 0** — independently reproduced (458 s). This is the ground truth, captured at the shipped HEAD, not the implementation commit.
- **Committed artifact:** `runtime/unittest_last_run.txt` → `test_count: 333`, `exit_code: 0`, `repo_root: C:/Users/gabot/agentic-os`, but `commit_full: 0a638bc` (off-branch — see F1). The 333/exit-0 **outcome** matches my run; the **commit reference** does not match the shipped implementation commit.

The handoff's outcome claim (333 / exit 0 at final HEAD) is **true** and reviewer-reproducible. The discrepancy is in *which commit the committed artifact attributes the run to*.

## Worktree Allocator Review — `dispatch/worktree_allocator.py` (+ registry, atomic_io)

Excellent, defense-in-depth. Verified:

- **Git is argv-only, `shell=False`, timeout-bounded, and subcommand-allowlisted** (`run_git`): only `rev-parse`, `status`, `worktree`, `merge-base`; `worktree` further restricted to `add`/`remove`/`list`/`prune`. No arbitrary git, no shell.
- **Branch/path sanitization** rejects control chars, `..`, and `@{` (git refspec injection); collapses unsafe chars; length-caps; regex-validates final branch; rejects leading/trailing slash and `//`.
- **Worktree path containment**: `build_worktree_path` resolves and asserts `path_is_inside(candidate, worktree_root)`; root is a sibling dir outside the repo (or `AGENTIC_OS_WORKTREE_ROOT`).
- **`git worktree add -b <branch> <path> <base_sha>`** after validating `base_sha` exists (`rev-parse --verify <sha>^{commit}`) and no active duplicate (run_id/branch/path).
- **Conservative cleanup**: refuses to remove a path git doesn't list as a worktree; refuses a **dirty** worktree (marks `preserved`); uses `git worktree remove` **without `--force`**; never `rm -rf`; never deletes outside the registered worktree; branches preserved.
- **`evaluate_allocation_for_execution`** binds the allocation to task_id/run_id/base_sha and confines both `cwd` and every `scope_path` inside the allocated worktree.
- **`atomic_io`**: `atomic_write_json` (tmp+fsync+`os.replace`) and `atomic_create_json` (`O_CREAT|O_EXCL`).

No safety gaps found.

## Approval Authenticity Review — `dispatch/approval_signing.py`

Cryptographically sound. Verified:

- **No secrets in repo**: keys read only from env (`AGENTIC_OS_REVIEWER_APPROVAL_KEY`, `AGENTIC_OS_HUMAN_APPROVAL_KEY`); reviewer/human key separation with separate `key_id`s.
- **HMAC-SHA256 over canonical JSON** (`sort_keys`, compact separators, signature excluded, paths posix-normalized); **`hmac.compare_digest`** constant-time comparison.
- **TTL caps**: human ≤ 30 m, reviewer ≤ 60 m; rejects TTL > max and ≤ 0; refuses to sign `blocked` level or already-expired records.
- **Verification binds the full scope** when a preview is supplied: `preview_hash`, `task_id`, `run_id`, `adapter_id`, `command` hash, `cwd`, `scope_paths` — any mismatch yields `stale`/`wrong_scope`; plus `revoked`/`expired`/`wrong_key` states. Anti-transplant and anti-replay-by-binding are thorough.
- Honest docstring: "local key possession, not legal identity." Accurate; matches the risk register.

## Anti-Replay Review — `dispatch/approval_replay.py`

- Path-traversal-safe `approval_id` (`^approval-[…]+$`, rejects `/`, `\`, `..`).
- **Single-use via `atomic_create_json` (O_EXCL)** → `FileExistsError` ⇒ `already_consumed`. Race-safe at the OS level.
- Claims stored at `runtime/dispatch/approval_consumed/<approval_id>.json`.

## Executor Integration Review — `dispatch/execution_gate.py`, `dispatch/executor.py`

- **File-writing execution requires an explicit allocation record** ("automatic allocation is not enabled"); the gate runs `evaluate_allocation_for_execution`, requires `base_sha`, and sets `effective_worktree_root` to the allocation's `worktree_path` so `worktree_policy` confines `cwd` to the worktree.
- **Signed-approval verification** runs in the gate for v2 records (verified against the live preview); **replay check** (`is_approval_consumed`) only on real execute.
- **Claim-before-subprocess**: the executor claims the approval (only when `operator_execute and not dry_run`) **before** `subprocess.run`; a failed claim (already consumed) blocks without executing. Dry-run neither claims nor consumes.
- Signed approval is enforced when a v2 record is present (infrastructure for future real-adapter promotion); the only executable adapter today is the `approval_level: none` fixture, so the path is built and tested but not yet load-bearing in production.

## Execution Boundary / Safety

| Check | Result |
|---|---|
| `shell=True` in dispatch | none |
| Runtime subprocess | `dispatch/executor.py` (agent) + `dispatch/worktree_allocator.py` (git allowlisted) only |
| `supports_execution: true` | 1 — `local-python-exec-test` only; all real adapters `false` |
| Autonomous allocation/execution from orchestrator/daemon/dashboard | none (only CLI hint text in a dashboard `<pre>`) |
| Dashboard execute/approve/allocate/sign endpoints | none (read-only) |
| Hardcoded secrets | none (env only) |
| `protocol/event_types.py` | unchanged — no premature event types |

All Phase 3.4 safety invariants hold. The milestone is operator-commanded only, Level 1, real adapters disabled.

## ADR and Protocol Review

- **ADR-0025** (worktree allocator), **ADR-0026** (HMAC approval), **ADR-0027** (single-use anti-replay), **ADR-0028** (Phase 3.4 execution boundary) — next unused numbers; in INDEX; no gaps/duplicates; each marked "accepted (… ), pending claude review" (not pre-flipped). Technically sound and matched to the implementation.
- **Reviewer approval is the appropriate level** for these; no human approval required.

## Critical Issues

None.

## High-Priority Issues

None. The branch is green at HEAD and the code is safe.

## Medium-Priority Issues

- **F1 — Committed verification artifact references a rebased-away commit.** `runtime/unittest_last_run.txt` records `commit_full: 0a638bc`, which is **not on the branch** (the implementation was rebased `0a638bc → ecec766`). The artifact was not regenerated after the rebase, so it attributes the 333/exit-0 run to a commit that no longer exists in history and disagrees with the handoff block's `tests_commit_sha: ecec766`. The branch is empirically green at HEAD (I confirmed), so the **outcome** is true — but the committed artifact does not faithfully record the shipped implementation commit. **Fix:** regenerate `runtime/unittest_last_run.txt` from the canonical clone at `ecec766` (or final HEAD) so `commit_full` is on-branch and equals `tests_commit_sha`.

- **F2 — `decisions/` added to the post-test allowlist.** `POST_TEST_ALLOWLIST_PREFIXES` now includes `"decisions/"`. Because ADRs are validated by `validate.py` (required sections, INDEX), this re-opens the gap I flagged as L-2 last round: a post-test ADR change can pass the verify CLI without the validator being re-run at HEAD. The cleaner resolutions, in order of preference: (a) have `verify_repository_verification.py` **re-run `scripts/validate.py` at HEAD and assert exit 0** (closes the whole class deterministically and makes the allowlist a secondary check), or (b) keep new ADRs in the implementation commit so they are covered by the tested tree, and drop `decisions/` from the allowlist.

- **F3 — Verify CLI does not cross-check the artifact against the block.** This is *why* F1 slipped through: the verify CLI reads `tests_commit_sha` from the handoff block but never checks that `runtime/unittest_last_run.txt`'s `commit_full` equals it (or is on-branch). **Fix:** have the verify CLI assert `artifact.commit_full == tests_commit_sha` (and that it is an ancestor of HEAD). Combined with F2(a), this makes "green at the shipped commit" machine-checked rather than self-reported.

## Low-Priority Issues

- **L-1 — Failed execution still consumes the approval** (claim happens before subprocess and is not rolled back). Documented and conservative-safe (re-approval required after any attempt); fine for the MVP, worth a note in the operator docs.
- **L-2 — Untracked scratch files** persist under `runtime/` and repo root; clean or gitignore.
- **L-3 — `git_status_clean` will be `false`** in handoffs while scratch files linger; addressing L-2 makes the verification block cleaner.

## Required Fixes (Phase 3.4.1 closeout)

1. **F1** — regenerate `runtime/unittest_last_run.txt` at `ecec766`/final HEAD so `commit_full` is on-branch and equals `tests_commit_sha`.
2. **F2** — resolve the `decisions/` allowlist widening: preferably make the verify CLI re-run `validate.py` at HEAD; otherwise move ADRs into the implementation commit and drop `decisions/` from the allowlist.
3. **F3** — verify CLI asserts `artifact.commit_full == tests_commit_sha` and is on-branch (closes the loophole that hid F1).

No changes to the worktree/HMAC/replay/executor logic are required — that code is correct and safe as written.

## Phase Readiness

**APPROVED WITH CHANGES — Phase 3.5 BLOCKED until the 3.4.1 closeout lands.**

The Phase 3.4 MVP is functionally complete, safe, and green at HEAD. It must not be treated as fully closed until F1–F3 are fixed and an independent re-run confirms green at the shipped commit with an on-branch artifact. Phase 3.5 (e.g., Level-2 queued scheduling per ADR-0024, or first real-adapter promotion per ADR-0023) must not begin. Any future real-adapter promotion still requires its own per-adapter ADR (ADR-0023 checklist), and the system must remain real-adapters-disabled / Autonomy Level 1 / operator-commanded.

## Recommended Next Milestone

**Phase 3.4.1 — Integrity closeout (F1–F3).** A < ½-day task: regenerate the artifact at the implementation commit, make the verify CLI re-run the validator at HEAD and cross-check the artifact SHA, and re-run from the canonical clone at the shipped HEAD with a truthful block. After an independent re-run confirms green at the shipped commit with `artifact.commit_full == tests_commit_sha`, I will flip the **ADR-0025–0028** reviewer sign-offs and clear Phase 3.5.

## Final Reviewer Notes

The hard engineering here is the best in the project. The worktree allocator's git allowlist + no-`--force` + dirty-refusal + path-containment is exactly how you build filesystem-mutating automation safely; the HMAC module's env-only keys, constant-time compare, and full scope binding are textbook; the O_EXCL single-use claim and claim-before-subprocess ordering are correct. I went looking hard for a way to escape the worktree, forge or replay an approval, or trigger execution autonomously, and did not find one. Only the harmless `python -c "print(...)"` fixture can execute, and file-writing execution refuses to run without an explicit, run-bound allocation.

What keeps this from a clean APPROVE is, once again, the verification *paperwork* rather than the code: a committed artifact that points at a rebased-away commit, and an allowlist widened to cover validator-checked files instead of adopting the one robust fix I keep recommending — have the closeout step **re-run the fast validator at HEAD** and cross-check the artifact against the tested commit. Do that in 3.4.1 and the integrity protocol finally becomes self-proving instead of self-reported. The branch is green and safe today; make the record of that fact on-branch and machine-checked, and Phase 3.4 is a clean close.

---

### Reported facts

1. **Reviewed branch:** `agent/composer/T-PHASE3-4-WORKTREE-APPROVAL-MVP`
2. **Local HEAD:** `19732d988641eab3c61e8f4e232f282b97813603`
3. **Remote HEAD:** `19732d988641eab3c61e8f4e232f282b97813603` (matches local)
4. **Test count / exit code:** 333 tests, OK, exit 0 — independently reproduced **at actual HEAD `19732d9`**
5. **Validator:** passed, exit 0 at HEAD
6. **Verdict:** APPROVE WITH CHANGES
7. **Required fixes:** F1 artifact references rebased-away `0a638bc` (regenerate at `ecec766`); F2 `decisions/` allowlist widening (re-run validator at HEAD); F3 verify CLI cross-check artifact==tests_commit
8. **Phase readiness:** APPROVED WITH CHANGES — Phase 3.5 blocked until the Phase 3.4.1 integrity closeout
9. **Recommended next milestone:** Phase 3.4.1 — Integrity closeout (F1–F3); then flip ADR-0025–0028 sign-offs and clear Phase 3.5
