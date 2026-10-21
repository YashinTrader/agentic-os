"""Small dependency-free size-rotating log writer for supervisor processes."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RotatingLogWriter:
    def __init__(self, path: Path, *, max_bytes: int = 10 * 1024 * 1024, backups: int = 5) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _rotate(self) -> None:
        if self.backups <= 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backups}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size and current_size + len(encoded) > self.max_bytes:
            self._rotate()
        with self.path.open("a", encoding="utf-8") as handle:
            return handle.write(value)

    def flush(self) -> None:
        return None

    def fileno(self) -> int:
        raise OSError("RotatingLogWriter does not expose a persistent file descriptor")

    def log_json(self, event: dict[str, Any]) -> None:
        import json
        self.write(json.dumps(event, sort_keys=True) + "\n")
