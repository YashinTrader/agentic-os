"""Atomic JSON file writes for runtime artifacts."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


REPLACE_RETRY_SECONDS = 2.5


def replace_with_retry(source: str | Path, destination: str | Path) -> None:
    """Bound Windows sharing violations; other OS errors retain fail-fast behavior."""
    deadline = None
    delay = 0.025
    while True:
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            code = getattr(exc, 'winerror', None)
            transient = code in {32, 33} or (isinstance(exc, PermissionError) and code == 5)
            if not transient:
                raise
            now = time.monotonic()
            if deadline is None:
                deadline = now + REPLACE_RETRY_SECONDS
            remaining = deadline - now
            if remaining <= 0:
                raise
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, 0.2)


def atomic_write_text(path: Path, content: str) -> None:
    """Publish a complete, uniquely staged file, never truncate the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content.encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def atomic_create_json(path: Path, data: dict[str, Any]) -> None:
    """Create file exclusively; raise FileExistsError if present."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(path), flags)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
