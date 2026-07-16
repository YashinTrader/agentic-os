"""Deterministic Codex context bundle builder — no secrets, atomic writes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

MAX_CONTEXT_FILE_BYTES = 512_000
MAX_BUNDLE_TOTAL_BYTES = 2_000_000
BUNDLE_DIR_NAME = "codex_context"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _bounded_dump(data: Any, *, max_bytes: int = MAX_CONTEXT_FILE_BYTES) -> str:
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"context payload exceeds {max_bytes} bytes")
    return text


def _bounded_text(text: str, *, max_bytes: int = MAX_CONTEXT_FILE_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError(f"context text exceeds {max_bytes} bytes")
    return text


def bundle_root(repo_root: Path, run_id: str) -> Path:
    return repo_root / "runtime" / "dispatch" / "runs" / run_id / BUNDLE_DIR_NAME


def compute_bundle_hash(bundle_dir: Path) -> str:
    digest = hashlib.sha256()
    if not bundle_dir.exists():
        return hashlib.sha256(b"").hexdigest()
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "manifest.json":
            continue
        rel = path.relative_to(bundle_dir).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_context_bundle(
    repo_root: Path,
    *,
    run_id: str,
    task: dict[str, Any],
    plan: dict[str, Any] | None,
    preview: dict[str, Any],
    adapter_policy: dict[str, Any],
    worktree_path: str,
    base_sha: str,
    allowed_paths: list[str],
    forbidden_operations: list[str],
    verification_commands: list[str],
) -> dict[str, Any]:
    """Write bundle files atomically; return manifest with bundle_hash."""
    root = bundle_root(repo_root, run_id)
    root.mkdir(parents=True, exist_ok=True)

    instructions = _bounded_text(
        "\n".join(
            [
                "# Codex restricted execution instructions",
                "",
                f"Task: {task.get('id', '')}",
                f"Objective: {task.get('objective', '')}",
                "",
                "## Allowed scope",
                "Edit files only inside the allocated worktree.",
                "Do not merge, push, deploy, or access production systems.",
                "Do not inspect secrets or credentials.",
                "Do not run MCP tools or browser automation.",
                "",
                "## Verification",
                *[f"- {cmd}" for cmd in verification_commands],
                "",
                "## Handoff",
                "Produce a structured handoff per expected_handoff.md.",
            ]
        )
    )

    files: dict[str, Any] = {
        "task.yaml": yaml.safe_dump(task, sort_keys=False),
        "plan.json": _bounded_dump(plan or {}),
        "preview.json": _bounded_dump(preview),
        "context_pack.md": _bounded_text(str(preview.get("context_pack_excerpt", "")) or "# Context\n"),
        "adapter_policy.json": _bounded_dump(adapter_policy),
        "allowed_paths.json": _bounded_dump({"allowed_paths": allowed_paths}),
        "instructions.md": instructions,
        "expected_handoff.md": _bounded_text(
            "\n".join(
                [
                    "# Expected handoff",
                    "",
                    "- Summary of changes",
                    "- Files changed",
                    "- Verification commands run",
                    "- Open questions",
                    "- No merge/push/deploy performed",
                ]
            )
        ),
    }

    total = 0
    written: list[str] = []
    for name, content in files.items():
        size = len(content.encode("utf-8"))
        total += size
        if total > MAX_BUNDLE_TOTAL_BYTES:
            raise ValueError("context bundle total size exceeds limit")
        target = root / name
        _atomic_write(target, content)
        written.append(name)

    manifest_without_hash = {
        "run_id": run_id,
        "task_id": str(task.get("id", "")),
        "worktree_path": worktree_path,
        "base_sha": base_sha,
        "bundle_dir": str(root),
        "files": written,
        "created_at": utc_now(),
        "timeout_seconds": int(preview.get("timeout_seconds") or adapter_policy.get("timeout_seconds") or 0),
        "approval_level": str(adapter_policy.get("approval_level", "human")),
    }
    _atomic_write(root / "manifest.json", json.dumps(manifest_without_hash, indent=2, sort_keys=True))
    bundle_hash = compute_bundle_hash(root)
    manifest = {**manifest_without_hash, "bundle_hash": bundle_hash}
    _atomic_write(root / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return manifest