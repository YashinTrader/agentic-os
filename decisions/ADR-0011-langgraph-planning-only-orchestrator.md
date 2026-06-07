# ADR-0011: LangGraph planning-only orchestrator (no agent execution)

- Status: accepted
- Date: 2026-06-07
- Deciders: composer (implementer), claude (reviewer)
- Approval level: reviewer
- Supersedes: none
- Related: ADR-0010, ADR-0004, ADR-0005

## Context

Phase 2.4 needs structured planning outputs (team suggestion, context pack, risk
gate, verification commands) before Phase 3 agent dispatch. LangGraph provides a
clear node graph without requiring LLM providers.

## Decision

Introduce LangGraph **only** for a deterministic planning pipeline:

```
load_task → classify_task → suggest_team → compile_context → risk_gate → generate_plan → finalize
```

Hard constraints:

1. **No LLM nodes** — no OpenAI/Anthropic/Gemini SDKs in orchestrator code.
2. **No agent execution** — plans set `executed_automatically: false`.
3. **No MCP execution** — MCPs listed in plans as metadata only.
4. **No task mutation** — orchestrator never changes task `owner` or `status`.
5. **Repo-sandboxed outputs** — default `runtime/orchestrator/runs`; `--output-dir` must stay inside repo unless `--allow-outside-repo`.
6. **Invalid tasks short-circuit** — `load_task` errors route to `persist_failure`; no plan/context generated; `next_action: fix_task_input`.
7. **Events** — successful finalize appends `orchestration_planned` (ADR-0010 / protocol extension).

CLI: `python scripts/orchestrate_task.py --task tasks/active/<id>.yaml`

Dashboard Orchestrator tab is **read-only** — displays `latest_state.json` / `latest_plan.json` only.

## Consequences

**Positive**

- Agent-ready artifacts without autonomous side effects.
- Graph structure documents the future dispatch pipeline explicitly.
- Risk gate surfaces human/reviewer approval before Phase 3.

**Negative**

- LangGraph dependency required (`pip install -r requirements.txt`).
- Team/skill classification is heuristic until richer matching exists.

**Neutral**

- Phase 3 may add execution nodes behind ADR-0012 gates; planning graph remains separate.

## Sign-off

- [x] composer (proposer/implementer)
- [ ] claude (reviewer — pending end-of-Phase-2 review)