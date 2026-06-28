"""LangGraph orchestrator for Agentic OS — planning only."""

from orchestrator.state import OrchestratorState

__all__ = ["OrchestratorState", "run_orchestration"]


def run_orchestration(*args, **kwargs):
    """Lazy import so dispatch preview and tests avoid requiring LangGraph at import time."""
    from orchestrator.graph import run_orchestration as _run_orchestration

    return _run_orchestration(*args, **kwargs)