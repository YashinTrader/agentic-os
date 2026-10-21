"""Shared runtime-state root selection for deploy entrypoints."""
import os
from pathlib import Path


def resolve_state_root(default, explicit=None):
    root = Path(explicit or os.environ.get("AGENTIC_OS_STATE_ROOT") or default).resolve()
    if not all((root / name).is_dir() for name in ("runtime", "agents")):
        raise ValueError(f"Invalid Agentic OS state root: {root} (requires runtime/ and agents/)")
    return root
