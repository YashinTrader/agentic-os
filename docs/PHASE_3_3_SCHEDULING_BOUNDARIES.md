# Phase 3.3 — Scheduling and Autonomy Boundaries

**Status:** design only  
**Enforced runtime level:** Level 1

## Autonomy levels

| Level | Name | Behavior |
|-------|------|----------|
| 0 | Preview only | Dry-run preview; no execution path |
| 1 | Explicit operator execution | Operator runs `execute_dispatch.py --execute` |
| 2 | Queued execution requiring approval | Future: queue holds requests; each needs approval |
| 3 | Policy-approved bounded automation | Future: cron-like within caps |
| 4 | Autonomous scheduling | Future: self-directed task pickup |

**Current system MUST remain at Level 1** through Phase 3.3.

## Prohibited behavior (now and in Phase 3.3 design)

- No automatic task pickup from `tasks/active/`.
- No recurring autonomous dispatch.
- No background agent launching.
- No silent retry loops.
- No auto-escalation to paid models.
- No auto-approval of human-gated tasks.
- No auto-merge or auto-push.
- No executing user-facing external actions (email, posts, payments).

## Future scheduler requirements

When Level 2+ is implemented (post Phase 3.3 review):

- Global and per-agent concurrency caps.
- Per-agent locks (one run per adapter instance).
- Task dependency checks before dispatch.
- Budget checks before paid API calls.
- Rate limits per adapter and per task type.
- Retry caps with exponential backoff.
- Cancellation API (SIGTERM → cleanup).
- Queue visibility (pending, running, dead-letter).
- Dead-letter state for exhausted retries.
- Operator pause per queue.
- Global emergency stop (drain + block new runs).

## Scheduler module boundary

A future `scheduler/` package may:

- Read queue state and emit plans.
- Enqueue approved requests.

It must NOT in Phase 3.3:

- Call `subprocess`.
- Invoke `execute_dispatch` without operator flag.
- Start daemon loops in production by default.