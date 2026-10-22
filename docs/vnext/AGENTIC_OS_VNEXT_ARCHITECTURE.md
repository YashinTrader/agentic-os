# Agentic OS VNext — Architecture

**Status:** Proposed · **Date:** 2026-10-21 · **Decision:** Option 1 (evolve the hardened runtime; replace the state layer)

## Design principles

1. **One control plane, one source of truth.** Agentic OS owns every orchestration decision. External tools may persist data or execute agents, but never decide.
2. **Verification is independent and executed.** A different vendor reviews, and it re-runs the gates. Reading a handoff is never verification.
3. **Every transition is transactional and recoverable.** No state change exists only in a file rename.
4. **Roles are configuration; models are replaceable.**
5. **Spend is a first-class signal.** Every run records cost or quota, and routing uses it.
6. **Humans approve consequences, not steps.**

## Layered architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Operator surface: dashboard · approvals inbox · alerts      │
├──────────────────────────────────────────────────────────────┤
│ Planning: goal → milestone → task contracts (Director role) │
├──────────────────────────────────────────────────────────────┤
│ Router: role × capability × budget × quota × history        │
├──────────────────────────────────────────────────────────────┤
│ Execution: supervisor · leases · watchdogs · adapters       │
│   claude | grok | codex | mimo | …  (isolated clone/sandbox)│
├──────────────────────────────────────────────────────────────┤
│ Verification: gates (deterministic) + cross-vendor reviewer │
├──────────────────────────────────────────────────────────────┤
│ Ledger (SQLite WAL; Beads candidate) · event log · memory   │
├──────────────────────────────────────────────────────────────┤
│ Governance: per-project policy · approvals · secrets bounds │
└──────────────────────────────────────────────────────────────┘
```

## Key components

### 1. Ledger (replaces JSON-file state) — *highest priority*

- A `TaskLedger` interface. Default backend: **SQLite in WAL mode** (stdlib, Windows-native). A Beads backend is evaluated in spike M2-S1.
- Tables: `tasks`, `assignments`, `runs`, `events` (append-only), `leases`, `verdicts`, `spend`.
- All transitions go through `transition(entity, from, to, evidence)`, inside a transaction with optimistic version checks. Illegal transitions are rejected centrally.
- **Recovery verbs** for every non-terminal state: `release`, `requeue`, `supersede`, `retry-after-condition-change`.
- **Work lock:** one active contract per task across all builders. This prevents the duplicate 9-6 build.
- JSON files remain as a read-only export for the dashboard and git history.

### 2. Supervisor and watchdogs

- Runs as a Windows service or Scheduled Task with triggers **at startup, at logon, and every 5 minutes** (`IgnoreNew`). A heartbeat file is checked by an independent watchdog.
- Children are supervised individually. If one child exits, only that child restarts, with backoff. Today, one child exiting kills the whole layer.
- Logs record **state changes only**, with size rotation. An idle tick is a metric, not a log line.

### 3. Event processing

- At-least-once delivery with idempotent handlers (fingerprint claims). Already proven live.
- **Deferred events carry a `blocked_on` condition**, such as `auth:claude`, `quota:grok`, or `human:approval`. They are re-evaluated when that condition changes, with exponential backoff, and escalate after N hours. This replaces the 111k-iteration defer loop.

### 4. Router

Inputs are the task's role, required capabilities, risk, and budget class, plus each provider's live quota, recent success rate, and cost per accepted outcome.

**Default role map** (configurable in `config/roles.yaml`):

| Role | Default | Fallback | Rationale |
|---|---|---|---|
| Director / chief reviewer | Claude | — | Planning, review, acceptance |
| Primary integrator | Grok Build | Codex | Multi-file integration |
| Bounded implementation | Codex (Sol, low reasoning) | Grok | Cheap and reliable for narrow contracts |
| Inexpensive analysis | MiMo Flash | Claude Haiku | Triage, log analysis, summaries |
| Independent reviewer | Different vendor than builder | — | Enforced invariant |

Model identifiers are validated by a probe before routing. For example, `gpt-5.6-luna-max` is rejected on the current ChatGPT plan, so a probe must confirm the model is available.

### 5. Verification

- **Deterministic gates** first: tests, validator, closeout gate, SHA reachability, scope check. These are run by the system, not by the agent.
- **Reviewer** second: it receives gate results plus the diff, and it **must be able to re-run gates**. Its tool allowlist must match the host shell (fixes the BLOCKED reviewer finding).
- The handoff protocol gains a `known_exempt_failures` field, so honest reporting passes the gate.

### 6. Memory

- **Project memory:** decisions, conventions, and known defects, stored in the ledger. It is injected into each context bundle and capped.
- **Organizational memory:** cross-project patterns, such as "codex-cli ≥0.144 requires clone layout on Windows."
- Defer external memory products until the ledger exists.

### 7. Budget and quota

- Every run records tokens, cost or quota, and its outcome. Per-provider quota state (`ok`, `low`, `exhausted until T`) feeds the router.
- Per-project monthly caps. The router refuses or downgrades a run when it would exceed the cap.
- Policy model borrowed from Omnigent: `cost_budget` and `max_tool_calls` at project, agent, and run scope.

### 8. Governance and approvals

A per-project `policy.yaml` defines allowed paths, forbidden operations, required gates, and an approval-required action list. The default list is: merge to protected branches, push to `main`, deploy, credentials, paid-service changes, and external communications.

Approvals arrive in a dashboard inbox and are recorded as ledger events with the approver's identity.

### 9. Operator dashboard

- **Home:** what is running, what is blocked and why, what needs me, and spend this week.
- **Per project:** a kanban of tasks, with each card showing its evidence chain (gates, verdict, SHAs).
- Alerts for any unhandled terminal event older than 5 minutes, and for a stale heartbeat.

## Mission layer: AOS-MISSION-001 (approved 2026-10-22, built after M1 and M2-02)

The mission layer sits above the runtime. A **mission controller** owns a bounded mission and drives the supervisor, builders and reviewers through it. Each mission has:
- a goal and acceptance criteria
- a deadline (15–240 min)
- a budget
- a tool and risk envelope
- required verification gates

Every mission reaches exactly one terminal decision: **GO / FIX / BLOCKED / NO-GO**.

How the controller works:
- It reads and writes only through the ledger.
- It reuses the M1 runtime guarantees: work locks, owned process trees, run deadlines, graceful stop, crash-safe evidence.
- It schedules toward the earliest verified outcome, reserving time and budget for independent verification.

Mission deadlines are separate from agent-run startup, inactivity and overall deadlines. It is domain-neutral through plug-ins: executors, verifiers, evidence extractors and progress signals.

Full spec, state machine, schema, dashboard and acceptance tests: [AOS-MISSION-001](AOS-MISSION-001_DEADLINE_DRIVEN_MISSIONS.md).

Optimization objective: **validated useful work per hour and per unit of cost.**

## Explicit non-goals (next 90 days)

- No rewrite, and no adoption of an external orchestrator.
- No cloud deployment and no multi-user tenancy.
- No auto-merge to protected branches.

## Migration path

Run the ledger in dual-write behind the interface. Compare it with the JSON files for one week, then make the ledger authoritative and keep JSON as an export. Each step must be reversible.
