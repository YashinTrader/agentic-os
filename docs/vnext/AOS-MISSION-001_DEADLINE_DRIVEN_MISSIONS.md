# AOS-MISSION-001: Deadline-Driven Autonomous Missions

**Status:** approved by the product owner (2026-10-22) as a permanent core capability.
**Build order:** after the core runtime (M1) and the authoritative ledger (M2-01/M2-02).
**Owner:** Claude (Director). Gabriel (product owner) keeps every sensitive approval.

**Primary metric:** validated useful outcomes per hour and per unit of cost. These do not count as success: tokens spent, agents launched, elapsed time used, apparent activity.

## 1. Product specification

A **mission** is a bounded unit of autonomous work. It has a goal, measurable acceptance criteria, a deadline, a budget, a permitted tool and risk envelope, and required verification gates. It always ends in exactly one terminal decision, backed by durable evidence.

Missions are domain-neutral. Coding missions (builder → reviewer) are the first adapter, followed by research, QA, browser workflows and general-purpose agents. The controller depends on four domain plug-ins:
- **Executors**: agents and tools
- **Verifiers**: independent checks
- **Evidence extractors**: structured facts from artifacts
- **Progress signals**: what counts as meaningful progress

### Mission contract (summary)

The full schema is in [`schemas/mission_contract.schema.json`](schemas/mission_contract.schema.json).

| Field | Meaning |
|---|---|
| `goal` | One sentence stating the outcome |
| `acceptance_criteria[]` | Each criterion is measurable and has a verifier |
| `deadline_minutes` | One of 15, 30, 60, 120 or 240. 240 is the normal maximum; a longer deadline requires owner approval |
| `target_minutes` | Expected duration. The scheduler aims at this, not at the deadline |
| `budget` | Provider/model limits: token limit, money limit, allowed models, maximum attempts |
| `tools` / `risk` | Allowed tools, allowed paths, forbidden operations, network policy, approval-required actions |
| `verification_gates[]` | Required independent checks. Each declares its expected cost in time and money |
| `verification_reserve` | Time and budget held back for verification and the decision. Never spent on execution |
| `parent_mission_id` / `lessons_in[]` | Continuity from an earlier FIX decision, plus reusable lessons it applies |

### Terminal decisions (exactly one per mission)

| Decision | Meaning |
|---|---|
| **GO** | Every acceptance criterion is verified by an independent gate |
| **FIX** | Verified partial progress plus a precise diagnosis. The decision report becomes the contract of a new bounded mission |
| **BLOCKED** | Progress depends on something outside the mission: owner approval, credentials, quota, an external outage. The record names the unblocking action |
| **NO-GO** | The goal is not achievable as specified, or the evidence shows the approach should stop |

There is no "timed out" outcome. At the deadline the controller decides with the evidence it has. Missing evidence means FIX, BLOCKED or NO-GO, never GO.

## 2. Mission controller responsibilities

1. **Track** elapsed time, remaining budget, verified progress (acceptance criteria satisfied by verifiers, not agent claims), and the next required action.
2. **Detect** loops and stalls:
   - the same failure fingerprint repeated
   - unchanged artifacts after an attempt
   - retries with no new evidence
   - progress signals flat for N intervals
   - effort growing while verified progress stays flat
3. **Replan** when the evidence supports it: change strategy, decompose the work, or switch model or provider (cheapest competent first, escalating only on evidence). Every replan is recorded with the evidence that triggered it.
4. **Reserve** time and budget for independent verification and the decision. The scheduler never starts execution work that would cut into the reserve.
5. **Decide early.** As soon as the mandatory evidence is conclusive, either way, the controller decides immediately.
6. **Never** invent success, self-certify acceptance, or waive a safety gate or owner approval to meet a deadline.
7. **At the deadline:**
   - stop launching new work
   - checkpoint, then gracefully stop or terminate the remaining *owned* processes (Job Object or PID tree, validated by start time, never by name)
   - preserve all artifacts
   - produce the best decision the evidence supports
8. **Preserve** context and verified partial progress (artifacts, SHAs, passed gates, diagnosis) so a FIX can be started directly as a new bounded mission.
9. **Record** cost, accepted outcomes, elapsed time, unnecessary retries, model usage and human interventions.
10. **Hold** owner approvals for sensitive actions: protected merges, deployments, live-state changes, credentials, spending. A mission that needs one goes BLOCKED with a precise request; it does not wait and does not bypass.

### Deadline layering

The four layers are independent and must not be conflated.

| Layer | Scope | Example |
|---|---|---|
| Mission deadline | The whole mission, ending in a decision | 60 min |
| Agent-run overall deadline | One agent execution | 30 min |
| Agent-run inactivity deadline | No genuine progress events | 10 min |
| Agent-run startup deadline | No first activity | 3 min |

Run deadlines protect against hung processes. The mission deadline protects against unbounded missions.

Activity detection must recognize genuine streaming activity from each provider's native protocol. Lesson from R7: Grok `--output-format json` is silent until exit, so adapters must use a streaming format (`streaming-json`) or another verified progress signal. An adapter without an observable progress signal cannot be scheduled with an inactivity deadline shorter than its overall deadline.

## 3. Scheduling and optimization rules (permanent)

1. **Earliest verified outcome.** Finish as soon as the mandatory evidence is sufficient. The deadline is a ceiling, not a target.
2. **Target durations:**
   - bounded tasks: 5–30 min
   - normal integration: 30–90 min
   - full release cycles: 60–120 min
   - 240 min only when genuinely necessary
3. **No passive waiting.** Use event-driven completion and do useful, non-conflicting work on the critical path. No repeated status polling.
4. **Auto-advance** between ready stages (execution → verification → closeout → fault injection → E2E → decision) without manual handoffs.
5. **Safe parallelism.** Run independent work in parallel, but serialize anything whose measurements or isolation would be invalidated by contention: uncontested suites, recovery-time measurements, provider rate limits.
6. **Cheapest competent model and minimum effort first.** Escalate on evidence (a repeated failure class or a verifier rejection), never by default.
7. **Stop non-progressing approaches.** Preserve results, diagnose, change strategy.
8. **No artificial work.** Do not extend real executions to exercise edge cases; test those with realistic fixtures.
9. **Time accounting** in every report: productive work, tests, avoidable waiting, retries, model usage.

## 4. State machine

```
            ┌──────────┐ contract valid, approvals present
 DRAFT ────►│ READY    │──────────────────────────────┐
            └──────────┘                               ▼
                 ▲ owner approval        ┌──────────────────────┐
                 │                       │ EXECUTING            │◄─────────┐
            ┌──────────┐ needs approval  │ (launch, monitor,    │  replan  │
            │ BLOCKED  │◄────────────────│  progress tracking)  │──────────┘
            └──────────┘ (terminal unless└──────────┬───────────┘
                          re-opened as new mission) │ criteria claimed / reserve reached /
                                                    │ loop or stall detected / deadline - reserve
                                                    ▼
                                         ┌──────────────────────┐
                                         │ VERIFYING            │ independent gates only
                                         └──────────┬───────────┘
                                                    ▼
                                         ┌──────────────────────┐
                                         │ DECIDING             │ evidence → decision
                                         └──────────┬───────────┘
                         ┌───────────────┬──────────┴───────┬───────────────┐
                         ▼               ▼                  ▼               ▼
                        GO              FIX             BLOCKED           NO-GO
                    (terminal)   (terminal; spawns   (terminal; names   (terminal)
                                  child mission)      unblocking action)
```

**Transition rules:**
- `EXECUTING → EXECUTING` (replan) requires recorded evidence. At most K replans per mission.
- Reaching `deadline − verification_reserve` forces `EXECUTING → VERIFYING`. No new launches happen after this point. Owned runs are checkpointed or stopped.
- If verification cannot finish before the deadline, `DECIDING` uses the evidence available. An unverified criterion is unmet.
- Any critical invariant failure moves the mission straight to `DECIDING` with FIX or NO-GO. Examples: duplicate execution, a process killed outside its ownership boundary, an unaudited live-state change, an unapproved sensitive action.
- Every transition is an append-only ledger event with a timestamp, actor and evidence references.

## 5. Evidence trail and lessons

- **Ledger events.** Every state transition, launch, verifier result, replan, cost sample and human intervention, all keyed by `mission_id`.
- **Decision report:**
  - mission, contract hash and SHAs
  - decision and criterion-by-criterion evidence
  - time split (productive, tests, waiting, retries)
  - cost per provider
  - interventions and blockers
  - next concrete action
- **Lessons.** Structured, reusable findings with a trigger, the evidence, the rule and its scope. Example: "Grok json output is silent until exit → use streaming-json". The planner queries lessons when drafting new contracts.

## 6. Operator dashboard proposal

A single **Missions** view. It is optimized for decisions, not activity.

1. **Header KPIs**, last 24 h and 7 d:
   - validated outcomes per hour
   - cost per validated outcome
   - median time to decision
   - GO / FIX / BLOCKED / NO-GO mix
   - unnecessary-retry rate
2. **Active missions**, one row each:
   - goal
   - state
   - elapsed vs target vs deadline (bar with the verification-reserve marker)
   - budget burn
   - verified criteria (n/m)
   - progress trend (sparkline of verified progress, not activity)
   - next required action
   - loop or stall flag
3. **Needs owner**: BLOCKED missions with the exact approval or credential request and one-click context.
4. **Recent decisions**: report link, time split, cost, lessons produced.
5. **Mission detail**:
   - timeline of transitions
   - owned processes (PID or Job, start time)
   - run deadlines vs the mission deadline
   - evidence per criterion
   - replans with their triggering evidence

## 7. Acceptance tests (for the implementation)

| ID | Scenario | Expected |
|---|---|---|
| MT-01 | All criteria verified at 40% of the deadline | Decision GO immediately; no further launches |
| MT-02 | Builder claims done; verifier rejects | No GO; replan or FIX with the verifier evidence |
| MT-03 | Same failure fingerprint 3× with no artifact change | Loop detected; strategy or model change recorded or FIX; no 4th identical attempt |
| MT-04 | Deadline − reserve reached while a run is active | No new launches; owned run checkpointed or stopped; verification uses the reserve |
| MT-05 | Deadline reached with one criterion unverified | Decision FIX, BLOCKED or NO-GO; never GO |
| MT-06 | Action requires owner approval | BLOCKED with a precise request; the action is not executed |
| MT-07 | Budget cap reached mid-run | Stop launching; decide from evidence; cost recorded |
| MT-08 | FIX decision | Child mission contract generated with parent link, preserved artifacts and passed gates |
| MT-09 | Silent-start provider (no streaming) | Rejected at scheduling, or uses a verified progress signal; no false inactivity kill |
| MT-10 | Streaming provider active beyond the startup deadline | Not killed; activity is counted from native stream events |
| MT-11 | Deadline termination | Only owned processes terminated (Job or PID tree with start-time validation); decoy survives |
| MT-12 | Cheaper model succeeds | No escalation; the report shows the model used and its cost |
| MT-13 | Conclusive NO-GO evidence early | Immediate NO-GO; the remaining budget is not consumed |
| MT-14 | Controller crash and restart | Mission resumes from the ledger without duplicate launches; elapsed time includes the downtime |
| MT-15 | Metrics | Validated outcomes per hour and per cost are computed from the ledger, not from agent self-reports |

## 7a. Prerequisites now in place

These parts of M1 are already implemented and are reused directly:
- work lock
- owned process trees and Job Objects
- startup, inactivity and overall run deadlines
- Grok streaming activity
- graceful stop with an owned fallback
- crash-safe evidence
- audited recovery verbs

## 8. Incremental implementation plan

Builders follow the cheapest-competent rule: Codex Sol at low effort by default, medium for concurrency and recovery work.

| Phase | Deliverable | Depends on | Target |
|---|---|---|---|
| MS-0 | Contract schema plus validator; mission records in the ledger; decision-report generator from the ledger | M2-02 ledger authoritative | 1 cycle |
| MS-1 | Controller core: state machine, deadline/reserve scheduler, no launches after the cutoff, owned-process checkpoint/stop at the deadline (reuses T-M1-25 stop control) | MS-0, M1 | 1–2 cycles |
| MS-2 | Progress and loop detection: verifier-based progress, fingerprint repetition, artifact-delta checks, stall detection | MS-1 | 1 cycle |
| MS-3 | Replanning and model routing: cheapest-competent policy, evidence-triggered escalation, budget accounting per provider (with M2-03/M2-04) | MS-2, M2-04 | 1–2 cycles |
| MS-4 | FIX → child mission, lessons store and retrieval | MS-1 | 1 cycle |
| MS-5 | Operator dashboard (Missions view) and KPI metrics | MS-0..MS-3, M3-02 | 1–2 cycles |
| MS-6 | Domain adapters beyond coding: research, QA, browser workflows | MS-1..MS-4 | per adapter |

Each phase ships through the standard release policy: a decision within at most 4 hours, a real end-to-end task per cycle, and the acceptance tests above as gates.
