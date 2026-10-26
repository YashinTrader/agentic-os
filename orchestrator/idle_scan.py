"""Small polling snapshots; no watchers, persisted cache, or ownership authority."""
from __future__ import annotations

import os
import time
from pathlib import Path

RECOVERY_INTERVAL_SECONDS = 60
STATUS_LIVENESS_SECONDS = 30


def fingerprint(paths: list[Path]) -> tuple:
    """Use entry metadata, including file edits, rather than directory mtime alone.

    Windows supplies DirEntry metadata with enumeration. Do not follow symlinks.
    A racing/denied read invalidates the snapshot on the next poll.
    """
    rows = []

    def scan(path):
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        rows.append((entry.path, 'dir'))
                        scan(Path(entry.path))
                    elif entry.name.endswith('.json'):
                        stat = entry.stat(follow_symlinks=False)
                        rows.append((entry.path, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            rows.append((str(path), 'missing'))
        except OSError:
            rows.append((str(path), time.monotonic_ns()))

    for path in paths:
        scan(path)
    return tuple(sorted(rows))


class ScanGate:
    def __init__(self):
        self.snapshot = None
        self.last_scan = float('-inf')

    def due(self, snapshot, now: float) -> bool:
        return (snapshot != self.snapshot or now < self.last_scan or
                now - self.last_scan >= RECOVERY_INTERVAL_SECONDS)

    def record(self, snapshot, now: float) -> None:
        self.snapshot, self.last_scan = snapshot, now


def write_status(path, status, *, volatile, now=None):
    """Keep current diagnostics in memory; publish changes or bounded liveness."""
    import json
    from dispatch.atomic_io import atomic_write_json
    now = time.time() if now is None else now
    try:
        old = json.loads(path.read_text(encoding='utf-8'))
        age = now - path.stat().st_mtime
    except (OSError, ValueError):
        old, age = {}, STATUS_LIVENESS_SECONDS
    stable = lambda value: {k: v for k, v in value.items() if k not in volatile}
    if stable(old) != stable(status) or age < 0 or age >= STATUS_LIVENESS_SECONDS:
        atomic_write_json(path, status)
