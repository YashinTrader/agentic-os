"""Atomic JSON file writes for runtime artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


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