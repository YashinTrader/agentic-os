# Agentic OS — 90-Day Roadmap

**Start:** 2026-10-21 · **Owner:** Claude (Director) · **Product owner:** Gabriel

Each milestone has an exit gate backed by evidence. A milestone is not complete until its gate is met with recorded SHAs, test runs, and live demonstrations.

## Release policy (owner decision 2026-10-22)

Every candidate goes through an evidence-driven release cycle that reaches a documented **GO / FIX / ROLLBACK / NO-GO** decision within **at most 4 hours** of its start, and earlier when evidence permits.

**How a cycle runs:**
- A cycle stops immediately when a critical invariant fails.
- Focused tests run throughout development. The uncontested full suite runs once on the final candidate SHA, and again only if the SHA changes or new evidence requires it.
- Active evidence is preferred: real agent execution, independent review, state transitions, targeted fault injection, crash recovery, process-ownership checks.
- Every cycle includes at least one real builder-to-reviewer task.

**How a cycle ends:**
- At the deadline, the decision uses the evidence available. Missing required evidence means NO-GO or FIX, never automatic approval.
- Every cycle ends with a short decision report covering the candidate SHA, tests, real task results, recovery findings, time consumed, cost where available, blockers, and the next improvement.
- After a GO, work advances to the next milestone. Passive health telemetry continues as operational monitoring only; it is not a gate.

**What does not change:** owner approvals for protected merges, sensitive live-state changes, credentials and deployments. The shorter window does not relax safety requirements.

## M1 — Reliability floor (days 0–21)

**Goal:** The existing loop runs reliably with zero manual state repair, proven by active evidence: real cycles, fault injection, crash recovery. (The original 7-day unattended goal was replaced by the release policy on 2026-10-22.)

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

**Exit gate:** a GO release cycle on the deployed candidate, covering:
- uncontested full suite exit 0
- drills A–F passed, including crash mid-review and a silent-start real-format builder
- ≥3 real builder→reviewer cycles reaching a recorded verdict and state transition
- zero manual state repairs since the deployment, other than owner-approved audited cleanup
- `main` updated through an approved PR

Telemetry is supporting evidence only and never blocks M2.

## M2 — Durable ledger and routing (days 22–55)

| ID | Task | Builder |
|---|---|---|
| M2-S1 | **Spike:** Beads (`bd`) on Windows vs SQLite WAL, behind `TaskLedger`. Measure atomic claim under concurrency, crash recovery, install friction | Codex |
| M2-S2 | **Spike:** Omnigent in WSL running Claude + Grok harnesses; policy engine fit | Grok |
| M2-S3 | **Spike (experimental runtime):** Google Antigravity CLI (`agy`) adapter, default model `gemini-3.8-flash-medium`. Contract-conformant prototype plus a 10–15 task benchmark against Codex Sol 6.1 (and MiMo Flash if installed). Read-only analysis and isolated experiments only. See below | Codex |
| M2-01 | `TaskLedger` interface + chosen backend, dual-write | Grok |
| M2-02 | Ledger becomes authoritative; JSON export | Grok |
| M2-03 | Spend/quota capture per run; provider quota state | Codex |
| M2-04 | Router v1: role map + quota-aware fallback + model probe | Grok |
| M2-05 | MiMo Flash adapter for analysis role (if available locally) | Codex |

**Exit gate:** No JSON-only state transitions. The router chooses its fallback automatically on quota exhaustion (demonstrated). Spend is visible per accepted task.

### M2-S3 — Antigravity CLI adapter spike (owner request 2026-10-22)

Branch `agent/codex/T-M2-S3-ANTIGRAVITY-CLI-ADAPTER`, based on the M1 candidate. It does not modify the M1 candidate or the scheduled supervisor. Sequencing: the offline prototype may proceed alongside M1. Live probes and the benchmark run only when no M1 gating suite or drill is running. Production routing stays off until M1 passes **and** the owner explicitly approves activation.

Facts established on 2026-10-22 (orchestrator probe, `agy` 1.1.5):
- `agy -p` performs a silent keyring login (consumer auth). `agy models` does not, so pre-login it lists a stale local set without Gemini models.
- One bounded call with `--model gemini-3.8-flash-medium --mode plan --sandbox` resolved to `Gemini 3.8 Flash (Medium)` after login, returned exit 0 in 50.7 s, and wrote nothing to the workspace.
- Before login the resolver logs `defaulting to CCPA`. Silent model fallback is therefore possible and must be detected, not inferred from exit 0.
- 1.1.5 has no `--output-format`/`stream-json`/JSON-schema flag. The conversation ID and model label appear only in the CLI log. No token usage was observed in stdout or the log.

Spike requirements:
- Reuse the global work lock, isolated workspaces, Job Object process ownership (internal subagents are children of the run and count against its budgets), startup/inactivity/overall deadlines, and per-task MCP isolation, or document the gap as for Grok.
- Never pass `--dangerously-skip-permissions`. Use `--sandbox`; `--mode plan` for read-only analysis; workspace limited to the task worktree.
- Use a per-run `--log-file` as the evidence source for the model actually resolved, the conversation ID, auth, quota and model-unavailable events, permission soft-denials (including exit 0), and completion.
- Treat intermediate activity as liveness only. Accept only the terminal result plus independent verification.
- Classify auth, quota and model-unavailable conditions without token-wasting retries.
- Benchmark metrics: accepted completion, wall-clock time, tokens (where reported), human corrections, quality, task-specific strengths. Subscription allowance is reported separately from API spend.
- Deliverables: adapter design, prototype, test evidence, benchmark table, recommendation ENABLE / EXPERIMENTAL / REJECT.

## Track AOS-MISSION-001: Deadline-driven autonomous missions (permanent core capability)

Approved by the owner on 2026-10-22. It starts after the M1 exit gate and M2-02 (ledger authoritative), and runs in phases MS-0 to MS-6 as defined in [the spec](AOS-MISSION-001_DEADLINE_DRIVEN_MISSIONS.md#8-incremental-implementation-plan).

| Phase | Deliverable | Depends on |
|---|---|---|
| MS-0 | Contract schema plus validator, mission ledger records, decision reports | M2-02 |
| MS-1 | Controller: state machine, deadline/reserve scheduler, owned checkpoint/stop | MS-0 |
| MS-2 | Progress, loop and stall detection | MS-1 |
| MS-3 | Replanning and cheapest-competent model routing with budgets | MS-2, M2-04 |
| MS-4 | FIX → child mission, lessons store | MS-1 |
| MS-5 | Missions dashboard and KPIs | MS-3, M3-02 |
| MS-6 | Research, QA and browser adapters | MS-1..MS-4 |

**Exit gate per phase:** a GO release cycle that passes the phase's acceptance tests (MT-01..MT-15 subset) and completes a real mission end to end.

**Primary metric:** validated outcomes per hour and per unit of cost.

## Track AOS-WIN-001: Windows Desktop Distribution (owner decision 2026-10-23)

**Trigger:** on 2026-10-23, Smart App Control blocked the unsigned uv/Hermes venv interpreter.

**Goal:** one-click, per-user, signed installation with a bundled runtime and no mandatory Hermes, uv, Python, Git, WSL2 or Docker.

**Design:**
- Primary channel: MSIX through the Microsoft Store.
- Direct channel: a signed MSIX plus a bootstrapper.
- Bundled PSF CPython with hash-locked wheels and a binary inventory.
- Job Object supervisor host and a Tauri shell.
- Credential Manager secrets.

**Missions:** WIN-M01 to WIN-M10, each four hours or less. See `AOS-WIN-001_WINDOWS_DESKTOP_DISTRIBUTION.md` and `AOS-WIN-001_CLEAN_MACHINE_TEST_PLAN.md`.

**Scheduling:**
- WIN-M01 (runtime builder) runs now, because it also produces the signed bridge runtime that restores the owner's install.
- Restoration is **never** blocked on the public installer.
- Publisher identity, the Store account and the signing service are owner decisions.

## Scheduling and efficiency rules (owner directive 2026-10-22, apply to all work)

Four hours is a hard ceiling, not a target. Target durations: bounded tasks 5–30 min, integration 30–90 min, release cycles 60–120 min.
- Stop as soon as the mandatory evidence is sufficient.
- Use event-driven completion, not polling; do useful non-conflicting work while waiting.
- Auto-advance between ready stages.
- Parallelize safely: never contend with an uncontested suite or with recovery measurements.
- Use the cheapest competent model and minimum effort, and escalate only on evidence.
- Stop approaches that are not progressing.
- Test edge cases with realistic fixtures, never by extending real runs.
- Report a time split (productive, tests, avoidable waiting, retries) and model usage.

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
- Activating Antigravity (or any new runtime) for normal production routing
