# ADR-0010: Phase 2 file-based runtime registries (CLIs, skills, MCPs, teams, roles)

- Status: accepted
- Date: 2026-06-07
- Deciders: composer (implementer), claude (reviewer)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0001, ADR-0004, ADR-0005, ADR-0009

## Context

Phase 2.0–2.2 introduced runtime discovery and multiple YAML registries without a
central database. Agents need a deterministic, auditable way to discover CLIs,
skills, MCP adapters, teams, and roles before any dispatch layer exists.

Alternatives considered:

- SQLite or Postgres registry — rejected for Phase 2 (adds ops burden, secrets risk).
- In-memory only — rejected (not durable across sessions or dashboard reads).
- Git-only with no runtime artifacts — rejected (cannot reflect installed CLIs).

## Decision

Phase 2 uses **file-based registries** as the canonical runtime surface:

| Registry | Path | Writer |
|----------|------|--------|
| CLI inventory | `runtime/registry/cli_inventory.yaml` | `daemon` discovery |
| Daemon status | `runtime/status/daemon_status.json` | `daemon` |
| Skills | `skills/registry.yaml` | human/reviewer via PR |
| MCPs | `mcps/registry.yaml` | human/reviewer via PR |
| Teams | `teams/registry.yaml` | human/reviewer via PR |
| Roles | `roles/registry.yaml` | human/reviewer via PR |

Rules:

1. Registries are **read-mostly** in Phase 2; dashboard tabs are read-only.
2. Discovery daemon **observes only** — no agent launch, no MCP execution.
3. `scripts/validate.py` cross-checks registry references (skills ↔ MCPs, teams ↔ roles).
4. New registry fields require validator updates and reviewer approval (not human by default).

## Consequences

**Positive**

- Zero database dependency; Git remains audit trail.
- Dashboard and orchestrator read the same files as CLIs.
- Validator enforces schema before Phase 3 dispatch.

**Negative**

- Concurrent writes can race; Phase 2 assumes single-writer discipline per registry.
- Runtime CLI inventory reflects last daemon run, not live process state.

**Neutral**

- Phase 3 may add adapter manifests; registries remain source of policy metadata.

## Sign-off

- [x] composer (proposer/implementer)
- [ ] claude (reviewer — pending end-of-Phase-2 review)