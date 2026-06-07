# Handoff: T-SKILLS-MCPS-001
**From:** composer
**To:** claude
**Date:** 2026-06-07T15:00:00Z
**Task Status After Handoff:** review

## What I Did
- Created `skills/registry.yaml` with four canonical skills (implement-python-cli, build-streamlit-dashboard, summarize-logs, review-protocol-change) and full required metadata fields.
- Created `mcps/registry.yaml` with three planned MCP examples (obsidian-local-rest, filesystem, github) — no secrets, `command: null` for planned entries.
- Added `skills/examples/` and `mcps/examples/` template YAML files plus READMEs.
- Implemented `scripts/list_skills.py` and `scripts/list_mcps.py` with agent/risk/status filters and `--json` output.
- Extended `scripts/validate.py` for skills/MCP schemas, skill status enum, planned MCP command guardrails, and `required_mcps` cross-reference checks.
- Added dashboard **Skills** (`/?tab=skills`) and **MCPs** (`/?tab=mcps`) read-only tabs with filter forms.
- Wrote `docs/SKILLS_AND_MCPS.md` and minimal README Phase 2.1 section.
- Added `tests/test_skills_registry.py` and `tests/test_mcps_registry.py` (18 tests total).
- Ran builder-reviewer loop; addressed MEDIUM findings (skill status validation, MCP reference integrity, planned command rules, loader error returns).

## What Remains
- Claude end-of-Phase-2 governance review: skill/MCP approval semantics vs task `risk_level` / `requires_human_approval`.
- Human merge after review.
- Phase 2.2 — Team Registry + Role Assignment (not in scope).

## Decisions Made
- Canonical registries live in `skills/registry.yaml` and `mcps/registry.yaml`; `examples/` are templates only.
- `planned` MCPs must have `command: null` and `endpoint: null` per validator guardrail.
- Skill `status` enum: `active`, `planned`, `deprecated`, `disabled`.
- No new Python dependencies; PyYAML only.
- Dashboard registry tabs are GET-only filters; no registry mutation endpoints.

## Open Questions
- Should skill `required_clis` be cross-checked against `runtime/registry/cli_inventory.yaml` in Phase 2.2?
- When should `status: configured` MCPs require non-null `command` validation?

## How to Verify My Work
```bash
python scripts/list_skills.py
python scripts/list_skills.py --agent codex --risk medium
python scripts/list_mcps.py --status planned
python -m unittest tests.test_skills_registry tests.test_mcps_registry
python -m unittest
python scripts/validate.py
python dashboard/app.py
# Open http://localhost:8501/?tab=skills and /?tab=mcps
```

## Tests Result
```
Ran 92 tests — OK
tests.test_skills_registry: 9 tests
tests.test_mcps_registry: 9 tests
```

## Validator Result
```
Validation passed.
```

## Risks / Caveats
- Registries are metadata only; no runtime enforcement of `approval_level` yet.
- `GITHUB_TOKEN` is named in MCP metadata but never stored — operators must supply via env in future phases.
- Dashboard task write paths (ADR-0006) remain separate from registry read-only tabs.
- Skill/MCP filters use exact agent id match (case-insensitive).

## Recommended Next Action for Receiver
Review Phase 2.1 registry design against architecture docs and ADR intent. At end of Phase 2 review, confirm:
1. Risk/approval enums are sufficient for orchestration gates.
2. No secret leakage paths in registry or dashboard.
3. Planned vs configured MCP lifecycle is clear.

If approved, mark T-SKILLS-MCPS-001 `done` and plan **Phase 2.2 — Team Registry + Role Assignment**.