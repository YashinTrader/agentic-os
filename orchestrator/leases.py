"""Supervisor leases — enforce concurrency=1 and prevent duplicate launches."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dispatch.atomic_io import atomic_create_json, atomic_write_json

DEFAULT_MAX_CONCURRENCY = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def leases_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "supervisor_leases"


def supervisor_lock_path(repo_root: Path) -> Path:
    return leases_dir(repo_root) / "supervisor_concurrency.json"


def assignment_lease_path(repo_root: Path, assignment_id: str) -> Path:
    return leases_dir(repo_root) / f"assignment-{assignment_id}.json"


@dataclass
class Lease:
    lease_id: str
    assignment_id: str
    run_id: str
    holder: str
    acquired_at: str
    heartbeat_at: str
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def count_active_leases(repo_root: Path) -> int:
    root = leases_dir(repo_root)
    if not root.is_dir():
        return 0
    return sum(1 for p in root.glob("assignment-*.json") if p.is_file())


def try_acquire_concurrency(
    repo_root: Path,
    *,
    assignment_id: str,
    run_id: str,
    holder: str,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> tuple[Lease | None, str]:
    """Atomically acquire a concurrency slot and per-assignment lease."""
    if max_concurrency < 1:
        return None, "max_concurrency must be >= 1"
    if count_active_leases(repo_root) >= max_concurrency:
        return None, "blocked_capacity: maximum concurrency reached"

    leases_dir(repo_root).mkdir(parents=True, exist_ok=True)
    now = utc_now()
    lease = Lease(
        lease_id=f"lease-{assignment_id}",
        assignment_id=assignment_id,
        run_id=run_id,
        holder=holder,
        acquired_at=now,
        heartbeat_at=now,
    )
    try:
        atomic_create_json(assignment_lease_path(repo_root, assignment_id), lease.to_dict())
    except FileExistsError:
        return None, f"assignment {assignment_id} already has an active launch lease"
    except OSError as exc:
        return None, f"failed to create assignment lease: {exc}"

    # Refresh concurrency snapshot for observability (best-effort).
    try:
        atomic_write_json(
            supervisor_lock_path(repo_root),
            {
                "max_concurrency": max_concurrency,
                "active": count_active_leases(repo_root),
                "updated_at": now,
                "holder": holder,
                "assignment_id": assignment_id,
                "run_id": run_id,
            },
        )
    except OSError:
        pass
    return lease, "acquired"


def heartbeat_lease(repo_root: Path, assignment_id: str, *, pid: int | None = None) -> None:
    path = assignment_lease_path(repo_root, assignment_id)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["heartbeat_at"] = utc_now()
    if pid is not None:
        data["pid"] = pid
    atomic_write_json(path, data)


def release_lease(repo_root: Path, assignment_id: str) -> None:
    path = assignment_lease_path(repo_root, assignment_id)
    if path.exists():
        path.unlink()
    # Update snapshot
    try:
        atomic_write_json(
            supervisor_lock_path(repo_root),
            {
                "max_concurrency": DEFAULT_MAX_CONCURRENCY,
                "active": count_active_leases(repo_root),
                "updated_at": utc_now(),
            },
        )
    except OSError:
        pass


def has_assignment_lease(repo_root: Path, assignment_id: str) -> bool:
    return assignment_lease_path(repo_root, assignment_id).is_file()
