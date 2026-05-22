# ADR-0001: Use Git Repo as Message Bus

**Status:** accepted
**Date:** 2026-05-22
**Author (agent):** human
**Reviewer (agent):** claude
**Approval:** human

## Context
Agents (Codex, Cursor, Claude, etc.) cannot yet communicate directly. We need
a coordination layer that works today, with zero infrastructure.

## Decision
Use a shared Git repository as the temporary message bus. All coordination
state (tasks, handoffs, decisions, logs) is stored as files in the repo.

## Alternatives Considered
1. Stand up a small HTTP service — rejected: premature, adds ops burden.
2. Use a shared SQLite file — rejected: harder to diff/review, not Git-friendly.
3. Use an MCP server now — deferred to Phase 2 when memory layer lands.

## Consequences
- Pro: zero infra, full Git history of every action, trivial onboarding.
- Pro: humans can review every change via PRs.
- Con: no real-time updates; agents poll by pulling.
- Con: merge conflicts possible — mitigated by branch-per-agent and append-only logs.

## References
- docs/ARCHITECTURE.md
