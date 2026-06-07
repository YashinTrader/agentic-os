# Phase 2 Review Packet

Prepared for Claude end-of-Phase-2 architecture review.  
Repository: [agentic-os](https://github.com/YashinTrader/agentic-os)  
Hardening task: `T-PHASE2-HARDENING-001`

## A. Phase 2.0 — Daemon Discovery

**Purpose:** Observe installed CLIs and agent tools; write machine-readable inventory for dashboard and future dispatch planning. No agent launch.

**Files:**

- `daemon/daemon.py`, `daemon/cli_discovery.py`, `daemon/registry_writer.py`
- `runtime/registry/cli_inventory.yaml`, `runtime/status/daemon_status.json`
- `docs/DAEMON_DISCOVERY.md`, `tests/test_cli_discovery.py`
- Dashboard tab: Agents / Tools (`/?tab=agents_tools`)

**Commands:**

```bash
python -m daemon.daemon --once
python -m daemon.daemon --watch   # optional polling
```

**Safety:** `shutil.which` + bounded subprocess probes; no `shell=True`; no network; no secrets; missing CLIs do not crash discovery.

**Limitations:** Point-in-time inventory; does not verify CLI auth or version compatibility; daemon not required for validator.

---

## B. Phase 2.1 — Skills + MCP Registry

**Purpose:** Catalog skills and MCP adapters as YAML registries for policy metadata (risk, approval, allowed agents). Read-only in Phase 2.

**Files:**

- `skills/registry.yaml`, `mcps/registry.yaml`
- `scripts/list_skills.py`, `scripts/list_mcps.py`
- `tests/test_skills_registry.py`, `tests/test_mcps_registry.py`
- Dashboard tabs: Skills, MCPs

**Commands:**

```bash
python scripts/list_skills.py
python scripts/list_mcps.py
python scripts/validate.py   # schema + cross-refs
```

**Safety:** No MCP execution; planned MCPs must have `command: null`; `requires_secret` flagged; dashboard read-only.

**Limitations:** Registry edits require PR/reviewer; no live MCP health checks; skill execution not implemented.

---

## C. Phase 2.2 — Teams + Roles

**Purpose:** Define teams, roles, and deterministic team suggestion for orchestration planning.

**Files:**

- `teams/registry.yaml`, `roles/registry.yaml`
- `scripts/suggest_team.py`, `scripts/list_teams.py`, `scripts/list_roles.py`
- `tests/test_teams_registry.py`, `tests/test_roles_registry.py`, `tests/test_team_suggestion.py`
- Dashboard tabs: Teams, Roles

**Commands:**

```bash
python scripts/suggest_team.py --task tasks/active/T-EXAMPLE.yaml
python scripts/list_teams.py
python scripts/list_roles.py
```

**Safety:** Suggestion is advisory only; no automatic task assignment; reviewer/human approval levels on roles.

**Limitations:** Heuristic scoring; planned teams deprioritized; does not mutate task `owner`.

---

## D. Phase 2.3 — Obsidian Sync

**Purpose:** One-way export of repo state (tasks, handoffs, ADRs, events) to a local Obsidian vault for human-readable knowledge.

**Files:**

- `integrations/obsidian/`, `memory/obsidian_mapping.yaml`
- `scripts/sync_obsidian.py`, `tests/test_obsidian_sync.py`
- Dashboard tab: Obsidian Sync (`/?tab=obsidian`)

**Commands:**

```bash
python scripts/sync_obsidian.py --dry-run
python scripts/sync_obsidian.py --vault /path/to/vault
```

**Safety:** Repo → vault only; no bidirectional sync; vault path validation; `sync_enabled` gate; dashboard does not trigger sync.

**Limitations:** Requires local vault path; not required for CI/validator; no conflict resolution for vault edits.

---

## E. Phase 2.4 — LangGraph Orchestrator

**Purpose:** Deterministic planning pipeline — classify skills, suggest team, compile context pack, risk gate, generate plan. No execution.

**Files:**

- `orchestrator/` package (graph, nodes, persistence, planner, risk)
- `scripts/orchestrate_task.py`
- `runtime/orchestrator/latest_state.json`, `latest_plan.json`, `runs/`
- `docs/LANGGRAPH_ORCHESTRATOR.md`
- `tests/test_orchestrator_*.py`, `tests/test_context_compiler.py`, `tests/test_risk_gate.py`
- Dashboard tab: Orchestrator (`/?tab=orchestrator`)

**Commands:**

```bash
python scripts/orchestrate_task.py --task tasks/active/T-EXAMPLE.yaml
python scripts/orchestrate_task.py --task tasks/active/T-EXAMPLE.yaml --json --dry-run
```

**Safety (post-2.5 hardening):**

- Output-dir repo sandbox (`--allow-outside-repo` override only)
- Invalid/missing tasks short-circuit; no misleading plan
- `executed_automatically: false` in plans
- Event: `orchestration_planned` on success

**Limitations:** LangGraph dependency; heuristic risk gate; dashboard read-only (no graph trigger).

---

## F. Current safety model

| Constraint | Status |
|------------|--------|
| No agent execution | ✅ Enforced |
| No MCP execution | ✅ Enforced |
| No LLM API calls | ✅ Enforced |
| No secrets in repo | ✅ Policy + review |
| No database | ✅ File-based only |
| No autonomous dispatch | ✅ ADR-0012 gates Phase 3 |
| Human approval for high-risk actions | ✅ Protocol + risk_gate hints |

---

## G. Claude review checklist

- [ ] **Architecture consistency** — Git-as-bus, file protocol, runtime artifacts align across 2.0–2.4
- [ ] **Protocol consistency** — Task schema v2, handoffs, ADRs, events
- [ ] **Validator coverage** — Registries, events, review docs, ADRs 0010–0012
- [ ] **Security** — Path traversal, output sandbox, no execution surfaces
- [ ] **Event vocabulary** — `protocol/event_types.py` matches docs and emitters
- [ ] **Approval model** — Human vs reviewer vs none boundaries
- [ ] **Phase 3 readiness** — `docs/PHASE_3_READINESS_CRITERIA.md` sufficient before dispatch work

**Related ADRs:** 0010 (registries), 0011 (planning orchestrator), 0012 (dispatch gates)

**Handoff:** `handoffs/T-PHASE2-HARDENING-001__composer__to__claude.md`