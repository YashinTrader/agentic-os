# LangGraph Orchestrator (Phase 2.4)

Phase 2.4 adds a **LangGraph-based planning layer** that reads a task, classifies
required skills, suggests a team, compiles a context pack, evaluates risk/approval,
and writes an orchestration plan.

## Purpose

Prepare structured outputs for future agent dispatch without executing agents in
this phase.

## Why LangGraph

LangGraph provides a explicit, inspectable graph of planning steps with durable
state — a foundation for Phase 2.5+ execution gates and conditional routing.

No LLM nodes are used. The graph is entirely deterministic.

## What the Graph Does

```
load_task → classify_task → suggest_team → compile_context → risk_gate → generate_plan → finalize
```

| Node | Responsibility |
|------|----------------|
| `load_task` | Parse task YAML (read-only) |
| `classify_task` | Infer required skills from labels, text, paths, registry |
| `suggest_team` | Score teams via existing `suggest_team` logic |
| `compile_context` | Write context pack MD/JSON for future prompts |
| `risk_gate` | Determine approval level (none / reviewer / human) |
| `generate_plan` | Write plan MD/JSON with verification commands |
| `finalize` | Persist latest state/plan; optional log event |

## What It Does NOT Do

- Execute Codex, Claude, Gemini, Cursor, OpenClaw, or other agents
- Call LLM APIs or MCPs
- Modify task owner or status
- Merge, push, or deploy
- Access secrets or perform network calls

## State Schema

See `orchestrator/state.py` — JSON-serializable fields include:

- `run_id`, `task_id`, `selected_team`, `required_skills`
- `approval_required`, `approval_reason`, `next_action`
- `context_pack_path`, `plan_path`, `errors`, `warnings`

## CLI Usage

```bash
python scripts/orchestrate_task.py --task tasks/active/T-OBSIDIAN-001.yaml
python scripts/orchestrate_task.py --task tasks/active/T-OBSIDIAN-001.yaml --json
python scripts/orchestrate_task.py --task tasks/active/T-EXAMPLE.yaml --dry-run
```

Install dependency:

```bash
pip install -r requirements.txt
```

## Runtime Outputs

| Path | Content |
|------|---------|
| `runtime/orchestrator/runs/<run_id>/context_pack.md` | Agent-ready context |
| `runtime/orchestrator/runs/<run_id>/context_pack.json` | Structured context |
| `runtime/orchestrator/runs/<run_id>/plan.md` | Human-readable plan |
| `runtime/orchestrator/runs/<run_id>/plan.json` | Machine-readable plan |
| `runtime/orchestrator/latest_state.json` | Latest run state |
| `runtime/orchestrator/latest_plan.json` | Latest plan summary |

## Safety Guarantees

1. Planning only — `executed_automatically: false` in every plan
2. Task files are never mutated
3. Risk gate escalates human approval for deploy/secrets/merge/production patterns
4. Log append uses `type: note` — compatible with event vocabulary
5. Dashboard orchestrator tab is read-only

## Future Phases

- **Phase 2.5** — End-of-Phase-2 hardening and Claude review packet
- **Phase 3.0** — Agent execution with approval gates and team dispatch

## Verification

```bash
python -m unittest tests.test_orchestrator_state tests.test_orchestrator_graph tests.test_context_compiler tests.test_risk_gate
python -m unittest
python scripts/validate.py
```