# Phase 2 Hardening Report

Task: `T-PHASE2-HARDENING-001`  
Date: 2026-06-07  
Scope: Phase 2.0–2.4 hardening before Phase 3 agent execution.

## Known limitations fixed

| Issue | Fix |
|-------|-----|
| `--output-dir` could write outside repo | `resolve_output_dir()` in `scripts/orchestrate_task.py` enforces repo containment; `--allow-outside-repo` explicit override |
| Graph continued after `load_task` errors | Conditional edge to `persist_failure`; downstream nodes no-op via `_wrap` |
| Invalid tasks could leave stale plans | `save_failed_latest()` writes error state, clears `latest_plan.json`, sets `next_action: fix_task_input` |
| Event vocabulary drift for Phase 2 | `protocol/event_types.py` canonical set; validator errors on unknown `type` |
| Orchestrator logged generic `note` | Successful finalize logs `orchestration_planned` |
| No Claude review bundle | `docs/PHASE_2_REVIEW_PACKET.md`, ADRs 0010–0012, this report |

## Known limitations remaining

| Issue | Severity | Notes |
|-------|----------|-------|
| Risk gate is keyword-heuristic | Medium | Not a substitute for human judgment |
| Team suggestion depends on registry completeness | Low | Planned teams score lower |
| Historical v1 `event` field in JSONL log | Low | Validator warns; migration optional |
| Daemon inventory is point-in-time | Low | Re-run `python -m daemon.daemon --once` |
| Obsidian sync requires local vault path | Low | Not required for validator/tests |
| LangGraph required for orchestrator | Low | Documented install path |
| No agent dispatch (by design) | N/A | Phase 3 gated by ADR-0012 |

## Test coverage summary

| Area | Test module |
|------|-------------|
| Output-dir sandboxing | `tests/test_phase2_hardening.py` |
| Graph short-circuit (missing/invalid task) | `tests/test_phase2_hardening.py`, `tests/test_orchestrator_graph.py` |
| Event vocabulary | `tests/test_phase2_hardening.py`, `tests/test_cli_guardrails.py` |
| Dashboard error state | `tests/test_phase2_hardening.py` |
| Review docs + ADRs | `tests/test_phase2_hardening.py`, `scripts/validate.py` |
| Phase 2.0–2.4 features | Existing suites (daemon, registries, obsidian, orchestrator) |

Run: `python -m unittest` and `python scripts/validate.py`

## Validator summary

`scripts/validate.py` checks:

- Task schema v2, handoffs, ADRs (including 0010–0012)
- Event log: required fields; **errors** on unknown `type` values
- Skills, MCPs, teams, roles registries and cross-references
- Obsidian mapping schema (vault not required)
- Phase 2 review packet files and required sections

Does **not** require: Obsidian vault, installed CLIs, MCP servers, latest orchestrator run.

## Risk register

| ID | Risk | Mitigation |
|----|------|------------|
| R1 | Accidental agent execution in Phase 3 | ADR-0012 gates; no execution code in Phase 2.5 |
| R2 | Path traversal via orchestrator output | Repo sandbox + tests |
| R3 | Misleading plan for bad task input | `persist_failure` path |
| R4 | Event vocabulary mismatch | Shared `protocol/event_types.py` |
| R5 | Dashboard write paths shell to CLIs | Existing guardrails; no new execute buttons |

## Recommended fixes before Phase 3

1. Implement dispatch adapter contract with dry-run-only default
2. Enforce approval gates in code (not heuristics only)
3. Migrate historical JSONL to ADR-0004 `type` field (optional cleanup task)
4. Add worktree-isolated execution harness with timeout/log capture

## Phase 2 readiness for Claude review

**Ready for Claude end-of-Phase-2 review.**

Phase 2.5 delivers hardening, governance docs, validator alignment, and a review
packet. Phase 3 agent execution remains explicitly out of scope and gated.