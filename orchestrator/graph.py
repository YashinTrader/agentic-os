"""LangGraph orchestration graph — planning only, no agent execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.loaders import safe_task_path
from orchestrator.nodes import (
    classify_task,
    compile_context,
    finalize,
    generate_plan,
    load_task,
    risk_gate,
    suggest_team,
)
from orchestrator.persistence import new_run_id, run_dir
from orchestrator.state import OrchestratorState, graph_dict_to_state, merge_state, state_to_graph_dict

try:
    from langgraph.graph import END, StateGraph
except ImportError as exc:
    raise ImportError(
        "LangGraph is required for orchestration. Install with: pip install -r requirements.txt"
    ) from exc


def _wrap(node_fn):
    def runner(state: dict[str, Any]) -> dict[str, Any]:
        current = graph_dict_to_state(state)
        if current.errors:
            return {}
        updates = node_fn(state)
        merged = merge_state(current, updates)
        return state_to_graph_dict(merged)

    return runner


def build_graph():
    graph = StateGraph(dict)
    graph.add_node("load_task", _wrap(load_task))
    graph.add_node("classify_task", _wrap(classify_task))
    graph.add_node("suggest_team", _wrap(suggest_team))
    graph.add_node("compile_context", _wrap(compile_context))
    graph.add_node("risk_gate", _wrap(risk_gate))
    graph.add_node("generate_plan", _wrap(generate_plan))
    graph.add_node("finalize", _wrap(finalize))

    graph.set_entry_point("load_task")
    graph.add_edge("load_task", "classify_task")
    graph.add_edge("classify_task", "suggest_team")
    graph.add_edge("suggest_team", "compile_context")
    graph.add_edge("compile_context", "risk_gate")
    graph.add_edge("risk_gate", "generate_plan")
    graph.add_edge("generate_plan", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_orchestration(
    repo_root: Path,
    task_path: str,
    *,
    dry_run: bool = False,
    no_log: bool = False,
    output_dir: str | None = None,
) -> OrchestratorState:
    repo_root = repo_root.resolve()
    resolved_task = safe_task_path(repo_root, task_path)
    run_id = new_run_id()

    out_path = output_dir or str(repo_root / "runtime" / "orchestrator" / "runs")
    if not dry_run:
        run_dir(repo_root, run_id, out_path).mkdir(parents=True, exist_ok=True)

    initial = OrchestratorState(
        run_id=run_id,
        task_path=str(resolved_task),
        repo_root=str(repo_root),
        output_dir=out_path,
        dry_run=dry_run,
        no_log=no_log,
    )

    app = build_graph()
    result = app.invoke(state_to_graph_dict(initial))
    return graph_dict_to_state(result)