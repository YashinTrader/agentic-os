"""Pure Codex CLI compatibility evaluation from read-only discovery data."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from dispatch.codex_adapter import CODEX_MINIMUM_VERSION, CODEX_OUTPUT_FLAG, CODEX_PROMPT_MODE, parse_semver, version_at_least

FORBIDDEN_HELP_FLAGS = frozenset(
    {
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
    }
)


@dataclass
class CliCompatibilityResult:
    compatible: bool
    record: dict[str, Any]
    incompatibility_reasons: list[str] = field(default_factory=list)


def _help_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_compatibility_record(discovery: dict[str, Any]) -> dict[str, Any]:
    version_raw = str(discovery.get("version_text", ""))
    parsed = ".".join(str(x) for x in parse_semver(version_raw) or ())
    exec_help = ""
    for inv in discovery.get("invocations") or []:
        argv = inv.get("argv") or []
        if isinstance(argv, list) and len(argv) >= 3 and argv[-2:] == ["exec", "--help"]:
            exec_help = str(inv.get("stdout") or "")
            break
        if isinstance(argv, list) and "exec" in argv and "--help" in argv:
            exec_help = str(inv.get("stdout") or "")

    output_flag = ""
    if exec_help:
        if (
            f"{CODEX_OUTPUT_FLAG}," in exec_help
            or f"{CODEX_OUTPUT_FLAG} " in exec_help
            or "--output-last-message" in exec_help
        ):
            output_flag = CODEX_OUTPUT_FLAG
    exec_available = bool(exec_help) and (
        "Usage: codex exec" in exec_help or "codex exec" in exec_help.lower()
    )

    record = {
        "executable_path": str(discovery.get("executable_path", "")),
        "version_raw": version_raw,
        "parsed_version": parsed,
        "inspected_at": discovery.get("discovered_at", ""),
        "exec_subcommand_available": exec_available,
        "output_flag": output_flag,
        "prompt_mode": CODEX_PROMPT_MODE,
        "supported_output_modes": ["jsonl", "last_message_file"],
        "supported_flags": ["-C", "-s", "--json", CODEX_OUTPUT_FLAG],
        "forbidden_flags": sorted(FORBIDDEN_HELP_FLAGS),
        "help_hash": _help_hash(exec_help) if exec_help else "",
        "compatible": False,
        "incompatibility_reasons": [],
    }
    return record


def evaluate_cli_compatibility(discovery: dict[str, Any], *, require_installed: bool = False) -> CliCompatibilityResult:
    record = normalize_compatibility_record(discovery)
    reasons: list[str] = []

    if require_installed and not record.get("executable_path"):
        reasons.append("Codex executable not found")
    if not record.get("exec_subcommand_available"):
        reasons.append("exec subcommand not available")
    if not record.get("output_flag"):
        reasons.append("required output option missing from CLI help")
    if record.get("prompt_mode") != CODEX_PROMPT_MODE:
        reasons.append("prompt mode mismatch")

    version_raw = str(record.get("version_raw", ""))
    if require_installed and version_raw and not version_at_least(version_raw, CODEX_MINIMUM_VERSION):
        reasons.append(f"CLI version below minimum {CODEX_MINIMUM_VERSION}")

    if require_installed and not record.get("help_hash"):
        reasons.append("CLI help hash unavailable; help not reviewed")

    record["incompatibility_reasons"] = reasons
    record["compatible"] = len(reasons) == 0
    return CliCompatibilityResult(compatible=record["compatible"], record=record, incompatibility_reasons=reasons)