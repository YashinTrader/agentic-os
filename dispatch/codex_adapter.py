"""Codex restricted adapter — pure command builder and gate evaluation (no subprocess)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dispatch.agent_context_bundle import bundle_root, compute_bundle_hash
from dispatch.agent_environment import environment_preview
from dispatch.path_containment import path_is_inside
from dispatch.worktree_allocator import evaluate_allocation_for_execution

CODEX_EXECUTABLE = "codex"
CODEX_MINIMUM_VERSION = "0.136.0"
CODEX_ALLOWED_SUBCOMMAND = "exec"
CODEX_SANDBOX_MODE = "workspace-write"

FORBIDDEN_FLAGS = frozenset(
    {
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "-s",
        "--sandbox",
    }
)

DANGEROUS_SANDBOX_VALUES = frozenset({"danger-full-access"})

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass
class CodexCommandPlan:
    argv: list[str]
    cwd: str
    environment_variable_names: list[str]
    scope_paths: list[str]
    expected_result_paths: dict[str, str]
    blocked_reasons: list[str] = field(default_factory=list)
    context_bundle_dir: str = ""
    context_bundle_hash: str = ""


def parse_semver(version_text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(version_text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def version_at_least(installed: str, minimum: str) -> bool:
    left = parse_semver(installed)
    right = parse_semver(minimum)
    if left is None or right is None:
        return False
    return left >= right


def load_codex_restricted_adapter(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "codex_restricted_adapter.yaml"
    if not path.exists():
        raise FileNotFoundError(f"codex restricted adapter config missing: {path}")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("codex_restricted_adapter.yaml root must be a mapping")
    return data


def _validate_adapter_contract(adapter: dict[str, Any]) -> list[str]:
    blocked: list[str] = []
    if adapter.get("id") != "codex-restricted":
        blocked.append("adapter id must be codex-restricted")
    if adapter.get("supports_execution"):
        blocked.append("codex-restricted must remain supports_execution=false in Phase 3.5")
    if adapter.get("promotion_state") != "restricted_candidate":
        blocked.append("promotion_state must be restricted_candidate")
    if adapter.get("approval_level") != "human":
        blocked.append("approval_level must be human")
    if not adapter.get("worktree_required"):
        blocked.append("worktree_required must be true")
    if not adapter.get("network_required"):
        blocked.append("network_required must be true")
    if not adapter.get("secrets_required"):
        blocked.append("secrets_required must be true")
    return blocked


def build_codex_command(
    adapter: dict[str, Any],
    *,
    repo_root: Path,
    worktree_path: str,
    run_id: str,
    stdout_path: str,
    stderr_path: str,
    agent_output_path: str,
    timeout_seconds: int,
    cli_version: str | None = None,
    allocation_record: dict[str, Any] | None = None,
    task_id: str = "",
    base_sha: str = "",
    scope_paths: list[str] | None = None,
) -> CodexCommandPlan:
    """Construct argv-only Codex exec invocation; does not execute."""
    blocked = _validate_adapter_contract(adapter)
    scope = list(scope_paths or ["."])

    worktree = Path(worktree_path).resolve()
    if not worktree.exists():
        blocked.append(f"worktree path does not exist: {worktree}")

    if cli_version is not None and not version_at_least(cli_version, str(adapter.get("minimum_version", CODEX_MINIMUM_VERSION))):
        blocked.append(
            f"installed Codex version {cli_version!r} below minimum "
            f"{adapter.get('minimum_version', CODEX_MINIMUM_VERSION)!r}"
        )

    bundle_dir = bundle_root(repo_root, run_id)
    instructions = bundle_dir / "instructions.md"
    if not instructions.is_file():
        blocked.append(f"context instructions missing: {instructions}")
    bundle_hash = ""
    try:
        bundle_hash = compute_bundle_hash(bundle_dir)
    except OSError:
        blocked.append("context bundle hash unavailable")

    if allocation_record is not None:
        blocked.extend(
            evaluate_allocation_for_execution(
                allocation_record,
                task_id=task_id,
                run_id=run_id,
                base_sha=base_sha,
                cwd=str(worktree),
                scope_paths=scope,
            )
        )
    elif adapter.get("worktree_required"):
        blocked.append("worktree allocation record required")

    env_preview = environment_preview(adapter)
    blocked.extend(env_preview.get("blocked_reasons") or [])

    allowed_flags = set(adapter.get("allowed_flags") or [])
    required_argv_tail = [
        CODEX_ALLOWED_SUBCOMMAND,
        "-C",
        str(worktree),
        "-s",
        CODEX_SANDBOX_MODE,
        "--json",
        "-o",
        agent_output_path,
    ]
    for token in required_argv_tail:
        if token.startswith("-") and token not in allowed_flags and token not in {"exec", CODEX_ALLOWED_SUBCOMMAND}:
            # exec subcommand and paths are structural, not free-form flags
            if token in FORBIDDEN_FLAGS:
                blocked.append(f"forbidden flag requested: {token}")

    for forbidden in adapter.get("forbidden_flags") or []:
        if forbidden in required_argv_tail:
            blocked.append(f"adapter forbids required structural token: {forbidden}")

    if timeout_seconds <= 0 or timeout_seconds > int(adapter.get("maximum_timeout_seconds", 3600)):
        blocked.append("timeout out of adapter bounds")

    argv = [
        str(adapter.get("executable", CODEX_EXECUTABLE)),
        CODEX_ALLOWED_SUBCOMMAND,
        "-C",
        str(worktree),
        "-s",
        CODEX_SANDBOX_MODE,
        "--json",
        "-o",
        agent_output_path,
    ]

    prompt_arg = f"Follow instructions in {instructions}"
    if len(prompt_arg) > 4000:
        blocked.append("constructed prompt exceeds size bound")
    argv[-1] = prompt_arg

    expected = {
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "agent_output_path": agent_output_path,
    }

    return CodexCommandPlan(
        argv=argv,
        cwd=str(worktree),
        environment_variable_names=list(env_preview.get("environment_variable_names") or []),
        scope_paths=scope,
        expected_result_paths=expected,
        blocked_reasons=blocked,
        context_bundle_dir=str(bundle_dir),
        context_bundle_hash=bundle_hash,
    )


def evaluate_codex_preview_gate(
    adapter: dict[str, Any],
    preview: dict[str, Any],
    *,
    cli_version: str | None = None,
) -> list[str]:
    """Additional preview-time checks for codex-restricted."""
    blocked = _validate_adapter_contract(adapter)
    if str(preview.get("adapter_id", "")) != "codex-restricted":
        blocked.append("preview adapter_id must be codex-restricted")
    command = str(preview.get("command", ""))
    for forbidden in adapter.get("forbidden_flags") or []:
        if forbidden in command:
            blocked.append(f"forbidden flag present in preview command: {forbidden}")
    for token in DANGEROUS_SANDBOX_VALUES:
        if token in command:
            blocked.append(f"dangerous sandbox mode in preview: {token}")
    if cli_version is not None and not version_at_least(cli_version, str(adapter.get("minimum_version", CODEX_MINIMUM_VERSION))):
        blocked.append("installed Codex CLI below minimum supported version")
    if adapter.get("supports_execution"):
        blocked.append("supports_execution must remain false until separate activation")
    return blocked