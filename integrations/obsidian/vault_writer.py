"""Safe filesystem writer for Obsidian vault sync."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Sanitize a filename or note stem for Obsidian."""
    cleaned = UNSAFE_FILENAME.sub("-", name.strip())
    cleaned = cleaned.strip(". ")
    return cleaned or "untitled"


def safe_join(vault_path: Path, vault_root_folder: str, relative: str) -> Path:
    """Resolve a path under vault_path/vault_root_folder; block traversal."""
    root = (vault_path / vault_root_folder).resolve()
    rel = relative.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise ValueError(f"relative path must not contain '..': {relative}")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes vault sync root: {relative}") from exc
    return target


@dataclass
class WriteResult:
    relative_path: str
    written: bool
    dry_run: bool


@dataclass
class VaultWriter:
    vault_path: Path
    vault_root_folder: str
    dry_run: bool = True
    folders_created: set[str] = field(default_factory=set)
    notes_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def sync_root(self) -> Path:
        root = (self.vault_path / self.vault_root_folder).resolve()
        try:
            root.relative_to(self.vault_path.resolve())
        except ValueError as exc:
            raise ValueError("vault_root_folder must stay inside vault_path") from exc
        return root

    def write_note(self, relative_path: str, content: str) -> WriteResult:
        target = safe_join(self.vault_path, self.vault_root_folder, relative_path)
        parent = str(target.parent.relative_to(self.sync_root))
        if parent != ".":
            self.folders_created.add(parent.replace("\\", "/"))
        if self.dry_run:
            return WriteResult(relative_path=relative_path, written=False, dry_run=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.notes_written.append(relative_path)
        return WriteResult(relative_path=relative_path, written=True, dry_run=False)

    def write_report(self, relative_path: str, report: dict) -> Path | None:
        import json

        content = json.dumps(report, indent=2, ensure_ascii=False)
        result = self.write_note(relative_path, content)
        if result.dry_run:
            return None
        return safe_join(self.vault_path, self.vault_root_folder, relative_path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")