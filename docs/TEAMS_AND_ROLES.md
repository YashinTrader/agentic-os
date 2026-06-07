# Teams and Roles (Phase 2.2)

Phase 2.2 adds **team and role registries** that map agents to responsibilities,
skills, MCP access, and approval policies — preparing Agentic OS for future
orchestration without executing agents or MCPs yet.

## What Teams Are

A **team** is a coordinated group of agents with:

- a purpose and orchestrator
- members (agent + role + skills + MCPs)
- required/optional skills and allowed MCPs
- approval policy and task suitability rules

Canonical file: `teams/registry.yaml`

## What Roles Are

A **role** defines an agent archetype:

- responsibilities and allowed agents
- required/optional skills and allowed MCPs
- governance (`risk_level`, `approval_level`)
- capability flags (`can_delegate`, `can_review`, `can_execute`)

Canonical file: `roles/registry.yaml`

## How Teams Relate to Skills and MCPs

| Layer | Relationship |
|-------|----------------|
| Skills | Teams declare `required_skills` / `optional_skills`; members list per-agent skills |
| MCPs | Teams declare `allowed_mcps`; members may list MCP access (metadata only) |
| Roles | Each member references a `role` id from `roles/registry.yaml` |
| CLI inventory | Not required for validation — capability planning only |

Cross-reference validation ensures skill, MCP, and role ids exist in their
respective registries.

## Approval Policy

Team `approval_policy` describes default governance:

```yaml
approval_policy:
  default_level: reviewer
  requires_human_for_high_risk: true
  notes: ...
```

This is configuration metadata in Phase 2.2. It does not auto-enforce approvals
until orchestration is implemented.

## Team Suggestion

`scripts/suggest_team.py` provides **deterministic, non-LLM** suggestions:

```bash
python scripts/suggest_team.py --task tasks/active/T-EXAMPLE.yaml
python scripts/suggest_team.py --skill build-streamlit-dashboard
python scripts/suggest_team.py --label dashboard
python scripts/suggest_team.py --json
```

Scoring considers:

- required/optional skill overlap
- task suitability labels and keywords
- title/objective keyword inference from tasks
- team status (planned teams score lower)

Output includes team id, score, matching/missing skills, recommended reviewer,
and notes. **No automatic task assignment.**

## CLI Helpers

```bash
python scripts/list_teams.py
python scripts/list_teams.py --status active
python scripts/list_teams.py --agent codex

python scripts/list_roles.py
python scripts/list_roles.py --agent claude
python scripts/list_roles.py --json
```

## Dashboard (Read-Only)

```bash
python dashboard/app.py
```

- **Teams** (`/?tab=teams`) — filters + optional task suggestion panel
- **Roles** (`/?tab=roles`) — filters by agent, risk, approval, execute/review flags

No registry editing or automatic assignment from the dashboard.

## Adding a New Role

1. Add entry to `roles/registry.yaml` with all required fields.
2. Optionally add `roles/examples/<id>.yaml`.
3. Ensure `required_skills` / `allowed_mcps` reference existing registry ids.
4. Run `python scripts/validate.py`.

## Adding a New Team

1. Add entry to `teams/registry.yaml` with members and policies.
2. Ensure orchestrator/default_reviewer appear in members or `external: true`.
3. Optionally add `teams/examples/<id>.yaml`.
4. Run `python scripts/validate.py` and test suggestion overlap.

## Why Phase 2.2 Does Not Run Agents

Execution requires:

- live agent processes and credentials
- MCP runtime and secret management
- approval enforcement and audit hooks

Phase 2.2 delivers **schemas, validation, visibility, and deterministic
suggestion** only.

## Preparation for LangGraph Orchestration

Future orchestration can consume:

- `teams/registry.yaml` — routing targets and member rosters
- `roles/registry.yaml` — permission and capability flags
- `skills/registry.yaml` + `mcps/registry.yaml` — dependency graph
- `suggest_team.py` — initial routing heuristic before graph-based flows

LangGraph (or equivalent) is **not** implemented in Phase 2.2.

## Verification

```bash
python -m unittest tests.test_roles_registry tests.test_teams_registry tests.test_team_suggestion
python -m unittest
python scripts/validate.py
```

## Next Step

**Phase 2.3 — Obsidian Vault Sync** (not implemented in this phase).