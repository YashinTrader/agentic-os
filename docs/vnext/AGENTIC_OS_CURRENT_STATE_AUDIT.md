# Agentic OS — Current State Audit

**Auditor:** Claude (Development Director / Chief Reviewer)
**Date:** 2026-10-21
**Repository:** `C:\Users\gabot\agentic-os` / `YashinTrader/agentic-os`
**Audit base:** `918b49b` (`agent/codex/T-PHASE3-9-6-ACTIVITY-DETECTION-FIX`)

Every claim below is tagged with its evidence level:

| Tag | Meaning |
|---|---|
| **LIVE** | Observed working end-to-end on this machine during the audit |
| **TESTED** | Unit/integration tests pass; not exercised live in this audit |
| **IMPL** | Code exists; no current test or live evidence |
| **BLOCKED** | Implemented but currently not functioning |
| **PROPOSED** | Design/contract only |

---

## 1. Executive summary

Agentic OS has, as of today, a **live-verified autonomous builder → reviewer → verdict loop**: a terminal builder poke was consumed by the Claude event consumer, which launched a real headless Claude process, received a schema-valid verdict, applied it to the assignment ledger, and archived the poke — with no chat message involved.

The system is **not yet reliable for unattended operation.** The supervisor died silently on 2026-10-20 and nothing restarted it; one stuck event was deferred ~111,000 times without re-evaluation; integration debt is severe (`main` is ~6 months and ~40 branches behind); and the headless reviewer could not execute any shell command, so its "independent verification" was document-reading only.

The foundation is worth keeping. The next 30 days should be spent on reliability and integration, not features.

---

## 2. Component status

| Component | Status | Evidence |
|---|---|---|
| Headless Claude reviewer (event consumer) | **LIVE** | 2026-10-21 16:53–16:55Z: fingerprint `2080508d…`, transitions `pending→claimed→review_starting→review_running→resolved`, PID 39484, session `c028c2ca-80ed-4775-8b54-dda84d81ba1b`, verdict `accepted`, assignment `assign-live-accept-9-6c` → `accepted`, poke archived to `pokes/consumed/`. ~100 s end to end. |
| Claude CLI authentication | **LIVE (fragile)** | `claude -p` returns OK; credential `expiresAt` 1792621715497 (~2026-10-21). OAuth expired mid-loop twice before (Aug 14, Oct). Not a durable headless credential. |
| Reviewer independent verification | **BLOCKED** | Same live run: reviewer reported *"PowerShell denied in this review session (dontAsk mode)"*; it ran **no** tests, validator, or closeout gates. Its allowlist uses `Bash(...)` patterns that do not match the Windows shell it is offered. Verdicts are currently evidence-reading, not evidence-producing. |
| Persistent supervisor (Task Scheduler) | **BLOCKED** | Task `AgenticOS Supervisor` state `Ready`, no processes. Log `supervisor-20261014-0700.log` ends `supervisor exited with code 1` at 2026-10-20 21:46 with no traceback. Trigger is `AtLogOn` only; restart policy does not cover a child exiting non-zero. |
| Supervisor logging | **IMPL (defect)** | 19.6 MB in 6 days; 111,985 `idle` + 111,687 `deferred` lines. No rotation, no state-change-only logging. |
| Deferred-event handling | **IMPL (defect)** | Fingerprint `1ddc9f2b…` deferred ~111k times across Sept–Oct; never retried after authentication recovered. No condition-change re-evaluation, no backoff, no escalation. |
| Event exactly-once / dedupe | **TESTED + LIVE** | Fingerprint claim files, `resolved/` record written before poke consumption (live run confirms ordering). 32/32 focused tests at `c374da7`. |
| Supervisor hardening (worktree isolation, Windows PID probe, failure lifecycle, max-turns resume) | **TESTED + LIVE** | Accepted at `7aa62a5`; supervisor survived orphaned run records; isolated worktree used for 9-5 Grok run. |
| Per-assignment MCP isolation | **TESTED** | Accepted at `2358b24`; 17/17 isolation tests; Codex `-c mcp_servers={}` override. Grok path is policy-only (documented gap). |
| Codex isolated execution | **LIVE (with caveats)** | codex-cli 0.159.2. Works in a **full clone**; worktree layouts rejected by Codex's Windows sandbox; `.git` writes blocked inside its sandbox, so the orchestrator commits with attribution; nested-sandbox launch from Claude requires disabling Claude's sandbox for that one command. |
| Grok isolated execution | **LIVE (prior)** | grok 1.0.24 alpha. 9-5 run (44 turns) in isolated worktree, terminated by 402 balance exhaustion; resumed and accepted. |
| Handoff integrity / closeout gate | **TESTED (protocol defect)** | `handoff_closeout_gate.py` enforces verify+validate. Six recurrences of stale-SHA handoffs before the gate. Protocol forces `test_exit_code: 0` even when a known-exempt test fails, so honest prose and the structured field disagree. |
| Leases / concurrency=1 | **TESTED** | Lease files; duplicate-launch prevention observed live in July. |
| Dashboard (read-only) | **TESTED** | `dashboard/app.py` 3,526 lines; serves on :8501. |
| Windows native | **LIVE** | Entire system runs natively. Encoding defect T-PHASE3-9-2 (cp1252) still open. |
| WSL | **Available, unused** | Ubuntu, WSL 2, running. |

## 3. Integration and ledger state

| Item | Finding |
|---|---|
| `origin/main` | `ee7d1ea` — Phase 3.3.2 (June). Nothing from Phases 3.4–3.9 is on `main`. |
| Unmerged lineage | `bfcfe55` → `7aa62a5` → `2358b24` → `3bdc02e` → `c374da7` → `918b49b` |
| **Correction to an earlier report** | `918b49b` was reported as pushed. It was pushed only to the local canonical repo (the build clone's `origin`), not to GitHub. GitHub had `c374da7`. Fixed in this audit's M1-00 task. |
| Duplicate work | Grok (`origin/agent/composer/T-PHASE3-9-6-ACTIVITY-DETECTION-FIX`, `dee4e9c`, 8 files, +575) and Codex (`918b49b`, 13 files, +447) independently implemented the same fix from `3bdc02e`. The orchestrator failed to prevent it. Codex's branch has live acceptance; Grok's is superseded. |
| Open PRs | #40 headless reviewer adapter (July, superseded by 9-6 lineage); #4 draft (May, stale). |
| Assignment ledger | 6 accepted, 2 awaiting_review (fixtures), 2 changes_requested, 2 claimed (stale since July), 1 superseded. Claimed assignments cannot be resolved with existing verbs. |
| Tasks | 35 active, 28 done, 4 blocked. Many `active` tasks are historical. |
| Worktrees | 15 registered, 86 MB. |
| Stashes | 3 forensic stashes preserved. |
| Code size | dispatch 9.0k, orchestrator 4.5k, scripts 8.3k, dashboard 3.6k, tests 13.1k lines; 43 ADRs. |

## 4. Root-cause themes

1. **State is a directory of JSON files.** Every reliability incident this quarter — stuck claims, deferred loops, orphan runs, stale outbox records, manual repair — traces to state transitions that are not transactional and have no recovery verbs.
2. **Process supervision assumes an interactive user.** Logon trigger, no liveness watchdog, children die with sessions.
3. **The verifier cannot verify.** Reviewer tool permissions do not match the host shell.
4. **Integration is not continuous.** Work accumulates on branches; `main` is not the source of truth; agents build on divergent bases.
5. **Orchestration lacks a work lock.** Two builders received the same contract.

## 5. Verification commands used

```
git rev-parse / git for-each-ref / git merge-base / git diff --stat
gh pr list --repo YashinTrader/agentic-os --state open
claude -p "reply exactly: ok" --model haiku
Get-ScheduledTask / Get-ScheduledTaskInfo / Win32_Process query
python scripts/assignments.py list|show
python scripts/run_claude_event_consumer.py --once   (live acceptance, isolated clone)
codex --version ; grok --version ; wsl -l -v
```
