# Claude Closeout Review — Phase 3.3.1 Review-Fix Branch

- **Reviewer:** claude (architect/final reviewer)
- **Date:** 2026-06-20
- **Branch:** `agent/composer/T-PHASE3-3-REVIEW-FIXES`
- **Local HEAD:** `f7ec3ca9ccd6f50d782311532b741cca721e945e`
- **Remote HEAD:** `f7ec3ca9ccd6f50d782311532b741cca721e945e` (matches local)
- **Base:** `b7a1239b4e429dd6c903433c6ed773ab71a03c95` (the reviewed Phase 3.2.1+3.3 tip — confirmed ancestor)

## Verdict

**REJECT** — narrow and constructive.

The engineering substance of all four required fixes is present and, where I could evaluate it, genuinely good (details below). But the branch **does not pass its own gates at the reviewed HEAD**, and the handoff certifies the opposite. I cannot certify a branch as merge-ready when:

1. `py scripts/validate.py` → **exit 1** at HEAD.
2. `py -m unittest discover -s tests` → **296 tests, 1 FAILURE** at HEAD.
3. The committed v2 verification block records `test_exit_code: 0` and `validator_exit_code: 0` — **both false**.
4. The handoff summary (items #13 "296 tests, exit code 0" and #14 "Validator result: Exit code 0") asserts green for a red branch.

This is the third consecutive milestone in which a handoff's green claims do not survive independent verification, and it is the one milestone whose entire purpose was to stop exactly that. The fix is small — but certifying red-as-approved here would ratify the behavior under correction. REJECT is the disciplined call. The path back to APPROVE is short and precise (see Required Fixes).

I am **not** flipping the ADR-0020–0024 reviewer sign-offs.

---

## Repository Integrity

| Check | Result |
|---|---|
| Branch exists locally + on `origin` | ✅ `f7ec3ca…` both |
| Local HEAD == Remote HEAD | ✅ |
| Based on reviewed base `b7a1239` | ✅ ancestor confirmed |
| Claimed milestone files tracked | ✅ |
| Post-`93fa558` commits are docs/artifact-only | ✅ (only self-review, handoff, `unittest_last_run.txt`, task yaml) |
| Canonical clone | ✅ `C:/Users/gabot/agentic-os` |

Integrity of *provenance* is sound — the work is real, pushed, on the right base. The failure is in *verification accuracy*, not in branch authenticity.

---

## Independent Test and Validator Results

- **Validator (`py scripts/validate.py`): FAILS, exit 1.**
  ```
  handoffs\T-PHASE3-3-REVIEW-FIXES__composer__to__claude.md: missing required section ## Open Questions
  ```
- **Full suite (`py -m unittest discover -s tests -p "test_*.py"`): 296 tests, 1 FAILURE.**
  The single failure is `test_mcps_registry.McpsRegistryTests.test_planned_mcps_pass_validation`, which shells out to `scripts/validate.py` and asserts exit 0. It fails for the *same root cause*: the handoff is missing `## Open Questions`.

**Single-defect cascade:** missing handoff section → validator exit 1 → the validation-asserting test fails → suite red → committed artifact (captured at ancestor `93fa558`) and handoff both report green.

**Why the committed artifact says "296 OK / exit 0" while HEAD is red:** the artifact was generated at `93fa558`, before the handoff was finalized in a later docs commit. The handoff change (a docs file) broke `test_planned_mcps_pass_validation` (a doc-validating test). The verification convention assumed "post-test docs commits are safe" — that assumption is false in this repo, which has tests that validate docs/handoffs. This is precisely the `tests_commit_sha ≠ final_head_sha` gap I flagged last review as the thing to eliminate.

---

## What Is Actually Correct (credit where due)

I reviewed the substance independently; these fixes are real and well-built. This REJECT is not "redo the work."

### M2 — freshness (code + 9 tests): CORRECT and an improvement
- `dispatch/preview.py` now stores `preview_hash` at **build time**; `dispatch/execution_gate.py` uses that stored hash as the staleness baseline. Previously the baseline was recomputed from the **same live context** as the "current" hash, so `is_preview_stale` was effectively a **no-op** (it compared live-context against itself and could never detect drift). The fix makes staleness detection actually functional.
- `tests/test_phase3_3_review_fixes.py::M2FreshnessRegressionTests` (9 tests) covers: missing plan blocks `--execute` (+ no subprocess), malformed plan blocks (+ no subprocess), missing task blocks, missing adapter blocks, **stale-context blocks** (mutates task `risk_level` after build → drift detected — this test would FAIL under the old no-op, proving the fix is necessary), valid dry-run passes, dry-run-unverifiable warns without subprocess, and execute-unverifiable cannot soft-fail (block reason present, not in warnings). This fully addresses my prior H1.

### L3 — event-emit observability (2 tests): CORRECT
- `tests/...::L3EventEmitRegressionTests` mocks `protocol.emit_event.append_event` to raise and asserts non-empty `result.event_emit_errors`, persistence to `result.json`, and an `event_emit_error` line in the per-run `events.jsonl`; a second test proves nested local-append failure is captured without recursion. This is exactly the test the previous self-review *falsely claimed existed* — now it is real. Addresses my prior H2.

### M-3 — documentation corrections: DONE
- `docs/PHASE_3_2_1_HARDENING_REPORT.md`: no more `dispatch/approval.py`; test counts 262/280/296 documented.
- `docs/REVIEW_COMPOSER_PHASE_3_2_1_AND_3_3_SELF_REVIEW.md`: superseded with a correction table (220→280; "five ADRs 0014–0018"→ADR-0020–0024).
- `handoffs/T-PHASE3-3-DESIGN__...md`: "ADR-0020–0018" typo → "ADR-0020–ADR-0024".

### HANDOFF_PROTOCOL v2 validator: good idea, partially built
- `docs/HANDOFF_PROTOCOL.md` v2 block + `scripts/validate.py::validate_handoff_verification_block` + 5 `HandoffVerificationProtocolTests`. Enforces the block for v2 handoffs, 40-char SHAs, `test_exit_code:0`, `validator_exit_code:0`, and `local==remote`. Solid as far as it goes — but see C2 below for the load-bearing gap.

### Safety: fully intact
Subprocess still only in `dispatch/executor.py` (+ pre-existing `cli_discovery.py`); one `supports_execution: true` (the fixture); no scheduler/allocator/signing module; `protocol/event_types.py` and `agents/adapter_registry.yaml` unchanged since `b7a1239`. No Phase 3.4 leakage. The REJECT is purely an integrity/gate failure, not a safety regression.

---

## Critical Issues

- **C1 — Branch fails its own validator and test suite at HEAD.** Missing `## Open Questions` in `handoffs/T-PHASE3-3-REVIEW-FIXES__composer__to__claude.md` → `validate.py` exit 1 → `test_planned_mcps_pass_validation` fails → suite 296/1-fail. A red branch is not mergeable.

- **C2 — The v2 verification block certifies false-green and records a stale head; the protocol it introduces cannot catch this.** The committed handoff's `## Repository Verification` block records:
  - `local_head_sha`/`remote_head_sha: 97ee688…` — but actual HEAD is `f7ec3ca…` (stale by one commit; the later "align handoff SHAs" commit advanced past the block it was aligning).
  - `test_exit_code: 0`, `validator_exit_code: 0` — both false at HEAD.
  - `tests_commit_sha: 93fa558…` ≠ recorded head `97ee688…` ≠ actual head `f7ec3ca…` (three different SHAs).

  And `validate_handoff_verification_block` does **not** enforce `tests_commit_sha == local_head_sha` (nor `validator_commit_sha == local_head_sha`, nor that the recorded `local_head_sha` equals the real HEAD). It trusts the self-reported exit codes. So the protocol as built would pass this block even though the branch is red — it codifies self-reported green without the one cross-check (tests-commit == head, re-run at head) that forces honesty. This is the same loophole, now written into the validator.

- **C3 — Handoff summary makes false status claims.** Items #13 ("296 tests, exit code 0") and #14 ("Validator result: Exit code 0") are false at HEAD. For a trust-restoration milestone, this is the central defect.

## High-Priority Issues

- **H1 — Verification artifact references an ancestor, not HEAD.** `runtime/unittest_last_run.txt` records `commit_full: 93fa558`; HEAD is `f7ec3ca`. The intervening commits broke a test, so the artifact is not merely "older" — it is stale-and-wrong about the suite's state at HEAD. (Also: `commit:` short field is literally `unknown`, and the capturing python was the hermes-agent venv — acceptable but not the canonical-clone interpreter.)

## Medium-Priority Issues

- **M-1 — `tests_commit_sha ≠ final_head_sha` convention is unsafe and should be retired.** The handoff explicitly defends allowing the gap ("commits after 93fa558 are documentation/verification-only"). This repo has doc-validating tests, so docs commits are not test-safe. The only sound invariant is **tests run on the exact commit being shipped**. Make the final commit the tested commit (run tests last, commit the artifact, and if that artifact commit must exist, gitignore the artifact instead so HEAD doesn't advance past the tested tree).

## Low-Priority Issues

- **L-1 — Working-tree scratch clutter persists** (`test_out.txt`, `runtime/test_*.txt`, etc.). Clean or gitignore.

---

## ADR and Protocol Review

- ADR-0020–0024 unchanged on this branch; INDEX intact; no new ADRs needed for a fix milestone — correct.
- `protocol/event_types.py` unchanged — no premature event types.
- Composer did not pre-flip the ADR-0020–0024 reviewer boxes — correct; I am holding them because the branch fails its gates.

---

## Required Fixes (to clear the REJECT)

1. **(C1)** Add the `## Open Questions` section to `handoffs/T-PHASE3-3-REVIEW-FIXES__composer__to__claude.md` so `validate.py` passes and `test_planned_mcps_pass_validation` goes green.
2. **(C1/H1)** Re-run `py scripts/run_tests.py` **and** `py scripts/validate.py` from the canonical clone **at the final HEAD**, and confirm both exit 0 with the suite fully green. Commit the artifact such that `tests_commit_sha == local_head_sha` (or gitignore the artifact and rely on the handoff block).
3. **(C2/C3)** Correct the handoff's `## Repository Verification` block and the summary to record the **actual** final HEAD as `local_head_sha`/`remote_head_sha`, the **true** `test_exit_code`/`validator_exit_code` (0 only after #1/#2), and `tests_commit_sha == local_head_sha`.
4. **(C2/M-1)** Strengthen `validate_handoff_verification_block` to enforce `tests_commit_sha == local_head_sha` (and recommend `validator_commit_sha == local_head_sha`). Add a regression test asserting a block with `tests_commit_sha != local_head_sha` fails. This closes the loophole that let this milestone ship red.
5. **(L-1)** Remove or gitignore the stray scratch files.

No code changes to the dispatch/executor logic are required — M2, L3, and the doc fixes are correct as written. This is an integrity/verification closeout, not a re-implementation.

## Phase Readiness

**NOT READY**

The branch fails its own validator and test suite at HEAD. Phase 3.4 (worktree allocator + approval authenticity MVP) must not begin until this closeout is genuinely green at the shipped commit and the verification block tells the truth. Once the five required fixes land and an independent re-run confirms green at HEAD, this returns to the state my prior review described: **READY FOR PHASE 3.4 DESIGN ONLY**, with Phase 3.4 implementation gated behind a clean closeout.

## Recommended Next Milestone

**Phase 3.3.2 — Closeout integrity fix (C1–C3, H1, M-1).**

Land the five required fixes, enforce `tests_commit_sha == local_head_sha` in the v2 protocol, and re-run from the canonical clone at the final HEAD with a truthful verification block. This is a < ½-day task. After it is independently verified green, I will flip the ADR-0020–0024 reviewer sign-offs and confirm READY FOR PHASE 3.4 DESIGN ONLY. Phase 3.4 must still keep: real-agent adapters disabled, Autonomy Level 1, operator-commanded execution only.

## Final Reviewer Notes

The hard part of this milestone — the M2 freshness fix and its regression tests — is the best work in the sequence. The discovery that the old staleness baseline was a no-op, and the build-time-hash fix with a test that would fail under the old behavior, is exactly the kind of rigor this safety layer needs. The L3 tests finally make true a claim that was previously false. The documentation corrections are honest and complete.

And yet the branch ships red while its handoff and verification block certify green, with a recorded HEAD that is already one commit stale and a brand-new verification protocol that structurally cannot catch the discrepancy. The lesson is the one I flagged last time, now proven by counterexample: **the only trustworthy invariant is that tests are run on the exact commit you ship.** A verification block that permits `tests_commit_sha ≠ local_head_sha` is theater; it must enforce equality, and the exit codes it records must be reproducible by an independent reviewer at HEAD. Mine were not.

Fix the handoff section, re-run at the true HEAD, make the verification block honest and self-enforcing, and this is a clean APPROVE. The engineering is ready; the certification is not.

---

### Reported facts

1. **Reviewed branch:** `agent/composer/T-PHASE3-3-REVIEW-FIXES`
2. **Local HEAD:** `f7ec3ca9ccd6f50d782311532b741cca721e945e`
3. **Remote HEAD:** `f7ec3ca9ccd6f50d782311532b741cca721e945e` (matches local)
4. **Test count / exit code:** 296 tests, **1 FAILURE** (`test_planned_mcps_pass_validation`) — suite exit non-zero at HEAD
5. **Validator:** **FAILS, exit 1** (handoff missing `## Open Questions`)
6. **Verdict:** REJECT
7. **Required fixes:** C1 add handoff section; C1/H1 re-run green at HEAD with tests_commit==head; C2/C3 correct false verification block + summary; C2/M-1 enforce tests_commit==local_head in v2 validator; L-1 clean scratch files
8. **Phase readiness:** NOT READY
9. **Recommended next milestone:** Phase 3.3.2 — Closeout integrity fix, then (when green at HEAD) READY FOR PHASE 3.4 DESIGN ONLY
