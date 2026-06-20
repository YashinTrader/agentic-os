"""Phase 3.4 single-use approval anti-replay for execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dispatch.atomic_io import atomic_create_json

APPROVAL_ID_RE = re.compile(r"^approval-[0-9A-Za-z._-]+$")


@dataclass
class ClaimResult:
    claimed: bool
    already_consumed: bool
    errors: list[str]
    claim_path: str | None = None


def _consumed_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "approval_consumed"


def validate_approval_id_for_claim(approval_id: str) -> list[str]:
    if not approval_id or not APPROVAL_ID_RE.match(approval_id):
        return [f"invalid approval_id for claim: {approval_id!r}"]
    if ".." in approval_id or "/" in approval_id or "\\" in approval_id:
        return ["approval_id must not contain path separators"]
    return []


def is_approval_consumed(repo_root: Path, approval_id: str) -> bool:
    path = _consumed_dir(repo_root) / f"{approval_id}.json"
    return path.exists()


def try_claim_approval(
    repo_root: Path,
    *,
    approval_id: str,
    run_id: str,
    task_id: str,
    preview_hash: str,
    execution_request_id: str,
) -> ClaimResult:
    """Atomically claim approval before subprocess execution."""
    errors = validate_approval_id_for_claim(approval_id)
    if errors:
        return ClaimResult(False, False, errors)

    claim = {
        "approval_id": approval_id,
        "run_id": run_id,
        "task_id": task_id,
        "preview_hash": preview_hash,
        "execution_request_id": execution_request_id,
        "status": "consumed",
    }

    path = _consumed_dir(repo_root) / f"{approval_id}.json"
    try:
        atomic_create_json(path, claim)
        return ClaimResult(True, False, [], claim_path=str(path))
    except FileExistsError:
        return ClaimResult(False, True, ["approval already consumed"], claim_path=str(path))
    except OSError as exc:
        return ClaimResult(False, False, [f"claim failed: {exc}"])


def load_claim(repo_root: Path, approval_id: str) -> dict[str, Any] | None:
    path = _consumed_dir(repo_root) / f"{approval_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None