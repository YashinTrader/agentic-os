# Orchestrator (Phase 2.4)

LangGraph-based **planning graph** for Agentic OS. Reads a task, classifies skills,
suggests a team, compiles a context pack, evaluates risk, and writes an
orchestration plan.

## Does NOT

- Execute agents (Codex, Claude, Gemini, etc.)
- Call LLM APIs or MCPs
- Modify task owner/status
- Merge, push, or deploy

## Entry Point

```bash
python scripts/orchestrate_task.py --task tasks/active/T-EXAMPLE.yaml
```

## Outputs

- `runtime/orchestrator/runs/<run_id>/context_pack.md`
- `runtime/orchestrator/runs/<run_id>/plan.json`
- `runtime/orchestrator/latest_state.json`
- `runtime/orchestrator/latest_plan.json`

See `docs/LANGGRAPH_ORCHESTRATOR.md`.