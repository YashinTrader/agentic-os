"""Read local-builder run artifacts from runtime/dispatch/runs/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def list_run_directories(repo_root: Path) -> list[Path]:
    runs_root = repo_root / "runtime" / "dispatch" / "runs"
    if not runs_root.is_dir():
        return []
    return sorted(
        [p for p in runs_root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def load_run_summary(run_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"run_id": run_dir.name, "run_dir": str(run_dir)}
    result_path = run_dir / "result.json"
    if result_path.is_file():
        try:
            summary.update(json.loads(result_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            summary["result_parse_error"] = True
    return summary


def list_run_summaries(repo_root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    return [load_run_summary(path) for path in list_run_directories(repo_root)[:limit]]