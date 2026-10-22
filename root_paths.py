"""Shared code/configuration and mutable-state root selection.

Libraries default to their caller's repository; entrypoints select and export
both roots once so spawned helpers use the same versioned configuration.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import subprocess
from subprocess import run as run_command
from pathlib import Path


def resolve_config_root(repo_root: Path, explicit=None, *, validate: bool = False) -> Path:
    selected = explicit or os.environ.get("AGENTIC_OS_CONFIG_ROOT")
    root = Path(selected or repo_root).resolve()
    # Legacy library fixtures may contain only the particular file under test.
    # Deployment entrypoints validate their default code checkout as well.
    if (selected or validate) and not all((root / name).is_dir() for name in ("agents", "config")):
        raise ValueError(f"Invalid Agentic OS config root: {root} (requires agents/ and config/)")
    return root


def resolve_state_root(default, explicit=None) -> Path:
    root = Path(explicit or os.environ.get("AGENTIC_OS_STATE_ROOT") or default).resolve()
    if not (root / "runtime").is_dir():
        raise ValueError(f"Invalid Agentic OS state root: {root} (requires runtime/)")
    return root


def export_roots(state_root: Path, config_root: Path) -> None:
    os.environ["AGENTIC_OS_STATE_ROOT"] = str(state_root)
    os.environ["AGENTIC_OS_CONFIG_ROOT"] = str(config_root)


def root_metadata(state_root: Path) -> dict:
    config_root = resolve_config_root(state_root)
    try:
        if not (config_root / ".git").exists():
            return {"config_root": str(config_root), "config_root_git_sha": None,
                    "state_root": str(Path(state_root).resolve())}
        result = run_command(["git", "-C", str(config_root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5, check=False)
        sha = result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        sha = None
    return {"config_root": str(config_root), "config_root_git_sha": sha,
            "state_root": str(Path(state_root).resolve())}


@contextmanager
def operator_roots(repo_root: Path, explicit=None):
    """Select CLI roots for one operation, preserving legacy explicit-root fixtures."""
    state = Path(explicit).resolve() if explicit is not None else resolve_state_root(repo_root)
    config = resolve_config_root(state if explicit is not None else repo_root)
    keys = ("AGENTIC_OS_STATE_ROOT", "AGENTIC_OS_CONFIG_ROOT")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ[keys[0]] = str(state)
        # Without an override, legacy explicit roots use library fallback, which
        # permits partial configurations and a not-yet-created runtime directory.
        if explicit is None or previous[keys[1]] is not None:
            os.environ[keys[1]] = str(config)
        yield state
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
