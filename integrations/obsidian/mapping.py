"""Load and validate Obsidian sync mapping configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAPPING_REL = Path("memory") / "obsidian_mapping.yaml"


def load_mapping(repo_root: Path) -> dict[str, Any]:
    path = repo_root / DEFAULT_MAPPING_REL
    if not path.exists():
        raise FileNotFoundError(f"{DEFAULT_MAPPING_REL.as_posix()} does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("obsidian_mapping.yaml root must be a YAML mapping")
    return data


def output_folders(mapping: dict[str, Any]) -> dict[str, str]:
    folders = mapping.get("output_folders", {})
    if not isinstance(folders, dict):
        raise ValueError("output_folders must be a mapping")
    return validate_output_folders({str(k): str(v) for k, v in folders.items()})


def _reject_traversal_segments(path_value: str, field_name: str) -> str:
    cleaned = path_value.strip().strip("/\\")
    if not cleaned:
        raise ValueError(f"{field_name} must be a non-empty path segment")
    if ".." in Path(cleaned).parts:
        raise ValueError(f"{field_name} must not contain '..' segments")
    return cleaned


def vault_root_folder(mapping: dict[str, Any]) -> str:
    root = mapping.get("vault_root_folder", "AgenticOS")
    if not isinstance(root, str) or not root.strip():
        return "AgenticOS"
    return _reject_traversal_segments(root, "vault_root_folder")


def validate_output_folders(folders: dict[str, str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for key, value in folders.items():
        validated[str(key)] = _reject_traversal_segments(str(value), f"output_folders.{key}")
    return validated


def resolve_vault_path(vault_arg: str | None, mapping: dict[str, Any]) -> Path | None:
    """Resolve vault path from CLI arg or mapping. Returns None for dry-run without vault."""
    configured = mapping.get("vault_path")
    chosen = vault_arg if vault_arg else configured
    if chosen is None or (isinstance(chosen, str) and not chosen.strip()):
        return None
    if not isinstance(chosen, str):
        raise ValueError("vault_path must be a string path")
    path = Path(chosen).expanduser().resolve()
    if ".." in Path(chosen).parts:
        raise ValueError("vault path must not contain '..' segments")
    if not path.exists():
        raise ValueError(f"vault path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"vault path is not a directory: {path}")
    return path


def require_explicit_vault_when_disabled(vault_arg: str | None, mapping: dict[str, Any]) -> None:
    if mapping.get("sync_enabled") is True:
        return
    if not vault_arg:
        raise ValueError(
            "sync_enabled is false in memory/obsidian_mapping.yaml; "
            "provide --vault for an explicit one-time sync"
        )