# Skills and MCP Registry (Phase 2.1)

Phase 2.1 adds **local-first registries** so Agentic OS knows which reusable
skills exist, which MCP servers are configured or planned, and what governance
(risk/approval) applies before any future orchestration.

## What Skills Are

A **skill** is a named, reusable capability with metadata:

- which agents may use it (`allowed_agents`)
- what CLIs or MCPs it depends on (`required_clis`, `required_mcps`)
- what files it typically touches (`required_files`, `outputs`)
- governance (`risk_level`, `approval_level`)

Canonical file: `skills/registry.yaml`

Example standalone templates: `skills/examples/*.yaml`

## What the MCP Registry Is

An **MCP entry** describes a Model Context Protocol server — transport,
capabilities, agent eligibility, secret requirements, and status.

Canonical file: `mcps/registry.yaml`

Example templates: `mcps/examples/*.yaml`

**Never store secrets** in registry files. Use `env_vars_required` to name
expected environment variables (e.g. `GITHUB_TOKEN`) without values.

## How They Relate to Agents

| Concept | Purpose |
|---------|---------|
| `allowed_agents` | Which agent identities may invoke this skill/MCP (future) |
| `required_clis` | CLIs that should be present (cross-check with daemon inventory) |
| `required_mcps` | MCPs a skill expects to be available (future) |
| `risk_level` | Operational risk if misused |
| `approval_level` | Who must approve before use |

Agents do **not** auto-run skills or MCPs in Phase 2.1. Registries are
observe/configuration only.

## Skill Status Values

| Status | Meaning |
|--------|---------|
| `active` | Registered and available for assignment metadata |
| `planned` | Documented but not yet active |
| `deprecated` | Superseded; avoid new assignments |
| `disabled` | Intentionally unavailable |

## Risk Levels

| Level | Meaning |
|-------|---------|
| `low` | Read-mostly, limited blast radius |
| `medium` | Code or protocol changes; reviewer attention |
| `high` | Secrets, filesystem, or external systems |

## Approval Levels

| Level | Meaning |
|-------|---------|
| `none` | No extra approval beyond normal task flow |
| `reviewer` | Reviewer agent must approve |
| `human` | Human must approve before execution (future) |
| `blocked` | Not permitted until explicitly unblocked |

## MCP Status Values

| Status | Meaning |
|--------|---------|
| `planned` | Documented intent only — valid in Phase 2.1 |
| `configured` | Config present locally but not verified running |
| `available` | Detected/confirmed available (future phases) |
| `disabled` | Intentionally off |
| `error` | Last check failed (future phases) |

`planned` MCPs **do not fail validation** and do not require local servers.

## CLI Helpers

```bash
python scripts/list_skills.py
python scripts/list_skills.py --agent codex
python scripts/list_skills.py --risk medium
python scripts/list_skills.py --json

python scripts/list_mcps.py
python scripts/list_mcps.py --status planned
python scripts/list_mcps.py --agent codex
python scripts/list_mcps.py --json
```

## Dashboard (Read-Only)

```bash
python dashboard/app.py
```

- **Skills** tab: `/?tab=skills` — filters by agent, risk, approval, category
- **MCPs** tab: `/?tab=mcps` — filters by agent, status

No registry editing from the dashboard in Phase 2.1.

## Adding a New Skill

1. Add an entry to `skills/registry.yaml` with all required fields.
2. Optionally add `skills/examples/<id>.yaml` as a template.
3. Run `python scripts/validate.py`.
4. Verify with `python scripts/list_skills.py --json`.

## Adding a New MCP

1. Add an entry to `mcps/registry.yaml` with all required fields.
2. Set `status: planned` unless locally configured.
3. Use `requires_secret: true` only when secrets are needed — never store values.
4. Run `python scripts/validate.py`.
5. Verify with `python scripts/list_mcps.py --json`.

## Why Phase 2.1 Does Not Execute MCPs

Execution introduces:

- secret handling and leak risk
- unbounded external API calls
- filesystem side effects
- agent autonomy concerns

Phase 2.1 establishes **schemas, validation, and visibility** first. Execution
gates belong in later phases with explicit human/reviewer approval wiring.

## Preparation for Teams and LangGraph

These registries become inputs for:

- **Phase 2.2 — Team Registry + Role Assignment** (which team owns which skills)
- **Future orchestration** (LangGraph or equivalent) mapping tasks → skills → MCPs
- **Policy engine** enforcing `risk_level` and `approval_level` before tool calls

The file-based protocol (tasks, handoffs, logs, ADRs) remains the coordination
backbone; registries add a structured capability layer on top.

## Verification

```bash
python -m unittest tests.test_skills_registry tests.test_mcps_registry
python -m unittest
python scripts/validate.py
```

## Next Step

**Phase 2.2 — Team Registry + Role Assignment** (not implemented in this phase).