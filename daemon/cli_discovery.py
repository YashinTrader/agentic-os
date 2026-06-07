"""Safe, read-only discovery of locally installed CLI tools and agents."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


DEFAULT_TIMEOUT_SECONDS = 5.0

RunFunc = Callable[[list[str], float], subprocess.CompletedProcess[str] | None]
WhichFunc = Callable[[str], str | None]


@dataclass(frozen=True)
class CliSpec:
    id: str
    display_name: str
    binary_names: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    conservative: bool = False


CLI_SPECS: tuple[CliSpec, ...] = (
    CliSpec("git", "Git", ("git",)),
    CliSpec("gh", "GitHub CLI", ("gh",)),
    CliSpec("python", "Python", ("python", "python3", "py")),
    CliSpec("node", "Node.js", ("node",)),
    CliSpec("npm", "npm", ("npm",)),
    CliSpec("uv", "uv", ("uv",)),
    CliSpec("streamlit", "Streamlit", ("streamlit",)),
    CliSpec("ollama", "Ollama", ("ollama",)),
    CliSpec("codex", "Codex CLI", ("codex",), conservative=True),
    CliSpec("claude", "Claude Code", ("claude",), conservative=True),
    CliSpec("gemini", "Gemini CLI", ("gemini",), conservative=True),
    CliSpec("cursor", "Cursor CLI", ("cursor",), conservative=True),
    CliSpec("opencode", "OpenCode", ("opencode",), conservative=True),
    CliSpec("aider", "Aider", ("aider",), conservative=True),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None


def _normalize_version_output(stdout: str, stderr: str) -> str | None:
    combined = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
    if not combined:
        return None
    first_line = combined.splitlines()[0].strip()
    return first_line or None


def _extract_version(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9.-]*)?)", text)
    if match:
        return match.group(1)
    cleaned = text.strip()
    return cleaned if cleaned else None


def _resolve_binary(spec: CliSpec, which_func: WhichFunc) -> tuple[str | None, str]:
    for name in spec.binary_names:
        path = which_func(name)
        if path:
            return path, "shutil.which"
    return None, "shutil.which"


def _detect_version(
    binary_path: str,
    spec: CliSpec,
    run_func: RunFunc,
    timeout: float,
) -> tuple[str | None, str | None, str | None]:
    args_to_try = spec.version_args
    if spec.conservative:
        args_to_try = ("--version", "-V", "version")

    last_command: str | None = None
    for arg in args_to_try:
        command = [binary_path, arg]
        last_command = " ".join(command)
        result = run_func(command, timeout)
        if result is None:
            continue
        if result.returncode != 0:
            continue
        raw = _normalize_version_output(result.stdout, result.stderr)
        version = _extract_version(raw)
        if version:
            return version, last_command, None

    if spec.conservative:
        note = "Version could not be determined safely; only path presence was confirmed."
    else:
        note = "Version command failed or returned no parseable version."
    return None, last_command, note


def discover_one(
    spec: CliSpec,
    *,
    which_func: WhichFunc | None = None,
    run_func: RunFunc | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    checked_at: str | None = None,
) -> dict[str, Any]:
    which = which_func or shutil.which
    run = run_func or _default_run
    timestamp = checked_at or utc_now()

    path, detection_method = _resolve_binary(spec, which)
    entry: dict[str, Any] = {
        "id": spec.id,
        "display_name": spec.display_name,
        "available": path is not None,
        "path": path,
        "version": None,
        "version_command_used": None,
        "detection_method": detection_method,
        "last_checked": timestamp,
        "notes": None,
    }

    if path is None:
        entry["notes"] = "CLI not found on PATH."
        return entry

    version, version_command, note = _detect_version(path, spec, run, timeout)
    entry["version"] = version
    entry["version_command_used"] = version_command
    if note and not version:
        entry["notes"] = note
    elif spec.conservative and version:
        entry["notes"] = "Version detected via conservative read-only probe."

    return entry


def discover_clis(
    *,
    which_func: WhichFunc | None = None,
    run_func: RunFunc | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    checked_at: str | None = None,
) -> dict[str, Any]:
    timestamp = checked_at or utc_now()
    tools = [
        discover_one(
            spec,
            which_func=which_func,
            run_func=run_func,
            timeout=timeout,
            checked_at=timestamp,
        )
        for spec in CLI_SPECS
    ]
    available_count = sum(1 for tool in tools if tool["available"])
    return {
        "schema_version": "1.0",
        "generated_at": timestamp,
        "discovery_method": "local_path_and_read_only_version_probe",
        "summary": {
            "total": len(tools),
            "available": available_count,
            "missing": len(tools) - available_count,
        },
        "tools": tools,
    }


def run_discovery(
    *,
    which_func: WhichFunc | None = None,
    run_func: RunFunc | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run a full discovery pass and return the inventory payload."""
    return discover_clis(which_func=which_func, run_func=run_func, timeout=timeout)