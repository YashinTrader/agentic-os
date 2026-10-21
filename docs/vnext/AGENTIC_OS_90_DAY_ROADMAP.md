# Agentic OS — 90-Day Roadmap

**Start:** 2026-10-21 · **Owner:** Claude (Director) · **Product owner:** Gabriel

Each milestone has an exit gate backed by evidence. A milestone is not complete until its gate is met with recorded SHAs, test runs, and live demonstrations.

## M1 — Reliability floor (days 0–21)

**Goal:** The existing loop runs unattended for 7 consecutive days with zero manual state repair.

| ID | Task | Builder | Notes |
|---|---|---|---|
| M1-00 | Publish `918b49b` to GitHub; mark duplicate Grok 9-6 branch superseded | Claude (ops) | Routine, non-protected branches |
| M1-01 | Supervisor restart resilience: startup + 5-min triggers, `IgnoreNew` | Claude (ops) | Local Task Scheduler config created earlier at owner request |
| M1-02 | Deferred-event re-evaluation + state-change-only logging + log rotation | Codex (Sol, low) | Fixes 111k defer loop / 19.6 MB log |
| M1-03 | Reviewer can execute gates on Windows (allowlist matches host shell) | Codex | Security-reviewed narrow allowlist |
| M1-04 | Per-child supervision with backoff (one child exiting ≠ layer exit) | Codex | |
| M1-05 | Handoff `known_exempt_failures` (was T-PHASE3-9-7) | Codex | |
| M1-06 | cp1252 encoding fix (T-PHASE3-9-2) | Codex | Unblocks clean full suite |
| M1-07 | Ledger recovery verbs for `claimed` / `reviewable_failure`; sweep stale assignments | Codex | |
| M1-08 | Work lock: one active contract per task across builders | Codex | Prevents duplicate builds |
| M1-09 | Integration branch → PR to `main` | Grok (integrator) | **Merge requires Gabriel's approval** |

**Exit gate:** 7-day unattended run log, zero manual repairs, ≥3 real builder→reviewer cycles, `main` updated through an approved PR.

## M2 — Durable ledger and routing (days 22–55)

| ID | Task | Builder |
|---|---|---|
| M2-S1 | **Spike:** Beads (`bd`) on Windows vs SQLite WAL, behind `TaskLedger`. Measure atomic claim under concurrency, crash recovery, install friction | Codex |
| M2-S2 | **Spike:** Omnigent in WSL running Claude + Grok harnesses; policy engine fit | Grok |
| M2-01 | `TaskLedger` interface + chosen backend, dual-write | Grok |
| M2-02 | Ledger becomes authoritative; JSON export | Grok |
| M2-03 | Spend/quota capture per run; provider quota state | Codex |
| M2-04 | Router v1: role map + quota-aware fallback + model probe | Grok |
| M2-05 | MiMo Flash adapter for analysis role (if available locally) | Codex |

**Exit gate:** No JSON-only state transitions. The router chooses its fallback automatically on quota exhaustion (demonstrated). Spend is visible per accepted task.

## M3 — Product surface and governance (days 56–90)

| ID | Task | Builder |
|---|---|---|
| M3-01 | Per-project `policy.yaml` + approval inbox | Grok |
| M3-02 | Dashboard home: running / blocked / needs-me / spend | Codex |
| M3-03 | Project and org memory in context bundles | Grok |
| M3-04 | Second project onboarded (multi-project proof) | Grok |
| M3-05 | Day-90 architecture re-evaluation (Omnigent / Beads results) | Claude |

**Exit gate:** Two projects run through the loop, approvals are recorded in the ledger, and Evaluation Plan metrics are reported against the M1 baseline.

## Decisions reserved for Gabriel

- Every merge to `main` or another protected branch
- Paid plan or quota changes (Grok balance, Codex/Claude plans, model tiers)
- Running services outside this machine (cloud sandboxes, hosted DB)
- Adopting any external substrate after the spikes
