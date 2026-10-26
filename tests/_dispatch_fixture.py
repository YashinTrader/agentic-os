"""Explicit audited dispatch opt-in for disposable launch fixtures."""
import os
from pathlib import Path
from unittest.mock import patch

from scripts.stop_supervisor import builder_dispatch


def resume_builder_dispatch(root: Path) -> None:
    """Resume only the caller's temporary state root, preserving the host guard."""
    with patch.dict(os.environ, {'AGENTIC_BUILDER_RUN_ID': ''}):
        result = builder_dispatch(root, 'resume', 'test', 'launch fixture')
    if result != 0:
        raise AssertionError(f'fixture dispatch resume failed: {result}')
