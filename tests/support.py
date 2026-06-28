"""Shared test helpers."""

from __future__ import annotations

import unittest

_LANGGRAPH_AVAILABLE: bool | None = None
LANGGRAPH_SKIP_REASON = (
    "langgraph not installed; run: pip install -r requirements.txt or python scripts/run_tests.py"
)


def langgraph_available() -> bool:
    global _LANGGRAPH_AVAILABLE
    if _LANGGRAPH_AVAILABLE is None:
        try:
            import langgraph.graph  # noqa: F401
        except ImportError:
            _LANGGRAPH_AVAILABLE = False
        else:
            _LANGGRAPH_AVAILABLE = True
    return _LANGGRAPH_AVAILABLE


def skip_without_langgraph(cls: type) -> type:
    return unittest.skipUnless(langgraph_available(), LANGGRAPH_SKIP_REASON)(cls)


def import_run_orchestration():
    from orchestrator.graph import run_orchestration

    return run_orchestration