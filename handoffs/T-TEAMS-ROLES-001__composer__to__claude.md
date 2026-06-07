# Handoff: T-TEAMS-ROLES-001 — Teams and Roles Registry

**From:** composer  
**To:** claude  
**Task:** T-TEAMS-ROLES-001  
**Phase:** 2.2  
**Status:** review

## What Was Built

Phase 2.2 adds local-first **team** and **role** registries with:

- Eight canonical roles with governance flags (`can_delegate`, `can_review`, `can_execute`)
- Five teams (dashboard, coding, review active; memory, research planned)
- Cross-reference validation against skills, MCPs, and roles
- CLI helpers: `list_teams.py`, `list_roles.py`, `suggest_team.py`
- Dashboard read-only **Teams** and **Roles** tabs with optional task suggestion panel
- Documentation in `docs/TEAMS_AND_ROLES.md`

No agents launched. No MCPs executed. No LangGraph. No Obsidian sync. No database.

## Files Changed

### New
- `roles/registry.yaml`, `roles/README.md`, `roles/examples/*.yaml` (8)
- `teams/registry.yaml`, `teams/README.md`, `teams/examples/*.yaml` (5)
- `scripts/list_teams.py`, `scripts/list_roles.py`, `scripts/suggest_team.py`
- `docs/TEAMS_AND_ROLES.md`
- `tests/test_roles_registry.py`, `tests/test_teams_registry.py`, `tests/test_team_suggestion.py`
- `tasks/active/T-TEAMS-ROLES-001.yaml`
- `handoffs/T-TEAMS-ROLES-001__composer__to__claude.md`

### Modified
- `scripts/validate.py` — roles/teams validation and cross-references
- `dashboard/app.py` — Teams, Roles tabs + read-only suggestion panel
- `README.md` — Phase 2.2 mention

## How to Run

```powershell
cd C:\Users\gabot\agentic-os
python scripts/list_teams.py
python scripts/list_teams.py --status active
python scripts/list_teams.py --agent codex
python scripts/list_roles.py --agent claude --json
python scripts/suggest_team.py --skill build-streamlit-dashboard
python scripts/suggest_team.py --task tasks/active/T-TEAMS-ROLES-001.yaml
python dashboard/app.py
```

Dashboard: `http://127.0.0.1:8501/?tab=teams`, `/?tab=roles`

## How to Verify

```powershell
python scripts/validate.py
python -m unittest
```

## Test Results

```
Ran 119 tests in ~1.5s — OK
```

Key coverage:
- Roles/teams load and required fields
- Invalid approval level / team status fail validation
- Missing skill, role, and MCP cross-references fail validation
- `suggest_team` returns `dashboard-team` for dashboard skill/tasks
- `suggest_team` returns `coding-team` for CLI skill/tasks
- Dashboard loaders handle missing registry files gracefully
- Path traversal rejected for `suggest_task` query param

## Validator Result

```
Validation passed.
```

## Risks / Caveats

1. **Capability planning only** — team registry does not verify agent CLIs are installed.
2. **Planned teams** score lower in suggestion but still appear in results.
3. **`grok` on research-team** has empty skills/MCPs — valid for research role metadata.
4. **Dashboard suggestion** uses inline import of `suggest_team` — deterministic, no LLM.
5. **No automatic assignment** — suggestion is advisory until orchestration phase.

## What Claude Should Review (End of Phase 2)

1. Governance alignment: role flags vs team approval policies
2. Cross-reference completeness across skills/MCPs/roles/teams
3. Whether planned teams (memory, research) have correct MCP/skill boundaries
4. Dashboard read-only guarantees and path safety on suggestion panel
5. Handoff quality and readiness for Phase 2.3 (Obsidian Vault Sync)

## Recommended Next Task

**Phase 2.3 — Obsidian Vault Sync**

- Wire `obsidian-local-rest` MCP metadata into memory-team workflows
- Define vault sync boundaries and write rules
- Still no autonomous agent execution until orchestration phase

---

*Composer — Phase 2.2 complete. Ready for reviewer pass.*