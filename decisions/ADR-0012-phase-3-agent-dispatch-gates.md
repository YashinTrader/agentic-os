# ADR-0012: Phase 3 agent dispatch gates (execution blocked until criteria met)

- Status: accepted
- Date: 2026-06-07
- Deciders: composer (implementer), claude (reviewer)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0011, docs/PHASE_3_READINESS_CRITERIA.md

## Context

Phase 2 delivers planning, registries, and observability. Phase 3 would add
agent execution — a high-risk capability that must not ship accidentally via
dashboard clicks, orchestrator defaults, or implicit MCP calls.

## Decision

**Phase 3 agent execution is blocked** until all gates in
`docs/PHASE_3_READINESS_CRITERIA.md` are implemented and verified.

Minimum gates (summary):

| Category | Requirement |
|----------|-------------|
| Execution | Explicit command only; dry-run mode; allowlisted adapters; preview; timeout; captured logs; task + handoff required |
| Approval | Human approval for secrets, spend, external side effects, CI/deploy, prod DB, destructive FS, main merge, security model changes |
| Reviewer | Protocol, validator, registry, and adapter changes |
| Sandbox | Repo-root containment; no path traversal; worktree isolation recommended |
| Logging | `run_id`, JSONL append, handoff, plan/context linkage |
| Rollback | Snapshot before file-writing agents; rollback steps in handoff |

Until gates pass:

- No autonomous dispatch loops.
- No dashboard "Run agent" buttons.
- No orchestrator auto-execution after `finalize`.
- No MCP tool invocation from core scripts.

## Consequences

**Positive**

- Prevents Phase 2 planning layer from becoming accidental production automation.
- Gives Claude/human reviewers a concrete checklist before Phase 3 work.

**Negative**

- Phase 3 delivery is slower; each gate needs tests and validator coverage.

**Neutral**

- Planning orchestrator remains available; only execution is gated.

## Sign-off

- [x] composer (proposer/implementer)
- [ ] claude (reviewer — pending end-of-Phase-2 review)