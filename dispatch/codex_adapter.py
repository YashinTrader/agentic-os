"""Codex restricted adapter — pure command builder and gate evaluation (no subprocess)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dispatch.agent_context_bundle import bundle_root, compute_bundle_hash
from dispatch.agent_environment import environment_preview
from dispatch.worktree_allocator import evaluate_allocation_for_execution

CODEX_EXECUTABLE = "codex"
CODEX_MINIMUM_VERSION = "0.136.0"


def resolve_codex_executable(name: str | None = None) -> str:
    """Resolve Codex CLI to an absolute path (required for Windows .cmd launch)."""
    candidate = (name or CODEX_EXECUTABLE).strip() or CODEX_EXECUTABLE
    if Path(candidate).is_file():
        return str(Path(candidate).resolve())
    resolved = shutil.which(candidate)
    return resolved or candidate
CODEX_ALLOWED_SUBCOMMAND = "exec"
CODEX_SANDBOX_MODE = "workspace-write"
CODEX_OUTPUT_FLAG = "-o"
CODEX_PROMPT_MODE = "positional_trailing"

FORBIDDEN_FLAGS = frozenset(
    {
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
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
    prompt: str = ""


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
    promotion = str(adapter.get("promotion_state", ""))
    scope = str(adapter.get("execution_scope", ""))
    if promotion == "restricted_candidate" and adapter.get("supports_execution"):
        blocked.append("restricted_candidate must have supports_execution=false")
    if promotion == "activation_candidate":
        if not adapter.get("supports_execution"):
            blocked.append("activation_candidate requires supports_execution=true")
        if scope != "canary_only":
            blocked.append("activation_candidate execution_scope must be canary_only")
    elif promotion == "restricted_execution":
        if not adapter.get("supports_execution"):
            blocked.append("restricted_execution requires supports_execution=true")
        if scope != "local_worktree":
            blocked.append("restricted_execution execution_scope must be local_worktree")
    elif promotion not in {"restricted_candidate", "activation_candidate", "restricted_execution"}:
        blocked.append(f"unsupported promotion_state: {promotion}")
    approval_level = str(adapter.get("approval_level", ""))
    if scope == "local_worktree":
        if approval_level not in {"none", "standing_policy"}:
            blocked.append("local_worktree approval_level must be none or standing_policy")
    elif approval_level != "human":
        blocked.append("approval_level must be human")
    if not adapter.get("worktree_required"):
        blocked.append("worktree_required must be true")
    if not adapter.get("network_required"):
        blocked.append("network_required must be true")
    if not adapter.get("secrets_required"):
        blocked.append("secrets_required must be true")
    return blocked


def build_codex_exec_options(
    adapter: dict[str, Any],
    *,
    worktree_path: str,
    agent_output_path: str,
) -> list[str]:
    """Validated option tokens before positional prompt (no prompt)."""
    return [
        CODEX_ALLOWED_SUBCOMMAND,
        "-C",
        str(worktree_path),
        "-s",
        CODEX_SANDBOX_MODE,
        "--json",
        CODEX_OUTPUT_FLAG,
        agent_output_path,
    ]


def append_codex_prompt(argv: list[str], prompt: str) -> list[str]:
    """Append positional prompt; never overwrite flag values."""
    if not prompt or not str(prompt).strip():
        raise ValueError("prompt must be non-empty")
    return [*argv, prompt]


def validate_codex_argv_contract(
    argv: list[str],
    *,
    executable: str = CODEX_EXECUTABLE,
    agent_output_path: str,
    prompt: str,
) -> list[str]:
    """Pure contract validation for codex exec argv shape."""
    blocked: list[str] = []
    if not argv:
        return ["argv must not be empty"]
    if argv[0] != executable:
        blocked.append(f"argv[0] must be {executable!r}")
    if CODEX_ALLOWED_SUBCOMMAND not in argv:
        blocked.append("missing exec subcommand")

    o_indices = [i for i, token in enumerate(argv) if token == CODEX_OUTPUT_FLAG]
    if len(o_indices) != 1:
        blocked.append(f"-o must appear exactly once; found {len(o_indices)}")
    else:
        o_idx = o_indices[0]
        if o_idx + 1 >= len(argv):
            blocked.append("missing value after -o")
        elif argv[o_idx + 1] != agent_output_path:
            blocked.append("token after -o must be agent output path")
        elif argv[o_idx + 1] == prompt:
            blocked.append("output path must not equal prompt")

    if prompt not in argv:
        blocked.append("prompt must appear in argv")
    elif argv.count(prompt) != 1:
        blocked.append("prompt must appear exactly once")
    elif argv[-1] != prompt:
        blocked.append("prompt must be trailing positional argument")

    for forbidden in FORBIDDEN_FLAGS:
        if forbidden in argv:
            blocked.append(f"forbidden flag present: {forbidden}")

    allowed_flags = {
        CODEX_ALLOWED_SUBCOMMAND,
        "-C",
        "-s",
        "--json",
        CODEX_OUTPUT_FLAG,
    }
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == prompt:
            break
        if token.startswith("-") and token not in allowed_flags:
            blocked.append(f"unknown or unsupported option: {token}")
            break
        if token in allowed_flags and token not in {CODEX_ALLOWED_SUBCOMMAND, "--json"}:
            i += 2
            continue
        i += 1

    return blocked


def compute_command_contract_hash() -> str:
    """Hash of the canonical argv template (options only, no paths/prompt)."""
    template = {
        "executable": CODEX_EXECUTABLE,
        "subcommand": CODEX_ALLOWED_SUBCOMMAND,
        "options": ["-C", "-s", CODEX_SANDBOX_MODE, "--json", CODEX_OUTPUT_FLAG],
        "prompt_mode": CODEX_PROMPT_MODE,
        "output_flag": CODEX_OUTPUT_FLAG,
    }
    payload = json.dumps(template, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    prompt: str | None = None,
) -> CodexCommandPlan:
    """Construct argv-only Codex exec invocation; does not execute."""
    blocked = _validate_adapter_contract(adapter)
    scope = list(scope_paths or ["."])

    worktree = Path(worktree_path).resolve()
    if not worktree.exists():
        blocked.append(f"worktree path does not exist: {worktree}")

    if cli_version is not None and not version_at_least(
        cli_version, str(adapter.get("minimum_version", CODEX_MINIMUM_VERSION))
    ):
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

    if timeout_seconds <= 0 or timeout_seconds > int(adapter.get("maximum_timeout_seconds", 3600)):
        blocked.append("timeout out of adapter bounds")

    prompt_arg = prompt if prompt is not None else f"Follow instructions in {instructions}"
    if len(prompt_arg) > 4000:
        blocked.append("constructed prompt exceeds size bound")

    argv = append_codex_prompt(
        [
            str(adapter.get("executable", CODEX_EXECUTABLE)),
            *build_codex_exec_options(
                adapter,
                worktree_path=str(worktree),
                agent_output_path=agent_output_path,
            ),
        ],
        prompt_arg,
    )
    blocked.extend(
        validate_codex_argv_contract(
            argv,
            executable=str(adapter.get("executable", CODEX_EXECUTABLE)),
            agent_output_path=agent_output_path,
            prompt=prompt_arg,
        )
    )
    for forbidden in FORBIDDEN_FLAGS:
        if forbidden in argv:
            blocked.append(f"forbidden flag present in argv: {forbidden}")

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
        prompt=prompt_arg,
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
    if cli_version is not None and not version_at_least(
        cli_version, str(adapter.get("minimum_version", CODEX_MINIMUM_VERSION))
    ):
        blocked.append("installed Codex CLI below minimum supported version")
    if adapter.get("promotion_state") == "restricted_candidate" and adapter.get("supports_execution"):
        blocked.append("supports_execution must remain false for restricted_candidate")
    return blocked