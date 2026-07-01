"""Codex local builder — standing-policy autonomous worktree development."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dispatch.agent_environment import (
    augment_codex_cli_environment,
    build_minimal_environment,
    codex_authentication_available,
    merge_allowlists,
)
from dispatch.codex_adapter import (
    build_codex_command,
    load_codex_restricted_adapter,
    resolve_codex_executable,
)
from dispatch.codex_local_builder_gate import evaluate_local_builder_gates
from dispatch.execution_route_policy import ROUTE_CODEX_LOCAL_BUILDER
from dispatch.local_builder_core import (
    CommandPlan,
    LocalBuilderRunConfig,
    SubprocessRunner,
    RESULT_BLOCKED,
    RESULT_COMPLETED_UNVERIFIED,
    RESULT_COMPLETED_VERIFIED,
    RESULT_FAILED,
    RESULT_SCOPE_VIOLATION,
    RESULT_TIMED_OUT,
    _git_changed_files,
    _parse_porcelain_changed_path,
    generate_run_id,
    run_adapter_local_builder,
    utc_now,
)

__all__ = [
    "RESULT_BLOCKED",
    "RESULT_COMPLETED_UNVERIFIED",
    "RESULT_COMPLETED_VERIFIED",
    "RESULT_FAILED",
    "RESULT_SCOPE_VIOLATION",
    "RESULT_TIMED_OUT",
    "LocalBuilderResult",
    "_git_changed_files",
    "_parse_porcelain_changed_path",
    "generate_run_id",
    "run_local_builder",
    "utc_now",
]

@dataclass
class LocalBuilderResult:
    run_id: str
    task_id: str
    status: str
    exit_code: int | None = None
    timed_out: bool = False
    worktree_path: str = ""
    allocation_id: str = ""
    handoff_path: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    verification_results: dict[str, Any] = field(default_factory=dict)
    run_dir: str = ""
    codex_subprocess_invoked: bool = False


CODEX_RUN_CONFIG = LocalBuilderRunConfig(
    adapter_id="codex-restricted",
    execution_route=ROUTE_CODEX_LOCAL_BUILDER,
    worktree_owner="codex-local-builder",
    agent_slug="codex",
    agent_output_relpath="runtime/codex_agent_output.json",
)


def _codex_command_plan(**kwargs: Any) -> CommandPlan:
    plan = build_codex_command(**kwargs)
    return CommandPlan(argv=plan.argv, cwd=plan.cwd, blocked_reasons=plan.blocked_reasons)


def _codex_prepare_environment(adapter: dict[str, Any]) -> tuple[dict[str, str], list[str], str | None]:
    allow = merge_allowlists(adapter.get("environment_allowlist"))
    deny = frozenset(adapter.get("environment_denylist") or [])
    env, env_names = build_minimal_environment(allowlist=allow, denylist=deny)
    auth_ok, auth_source = codex_authentication_available()
    if auth_ok:
        env, env_names = augment_codex_cli_environment(env)
    return env, env_names, auth_source


def run_local_builder(
    repo_root: Path,
    *,
    task_path: Path,
    base_sha: str | None = None,
    codex_executable: str | None = None,
    cli_version: str | None = None,
    subprocess_runner: SubprocessRunner | None = None,
    skip_codex: bool = False,
    fake_codex_exit: int = 0,
) -> LocalBuilderResult:
    """Execute one codex local-builder run. subprocess_runner injectable for tests."""
    adapter = load_codex_restricted_adapter(repo_root)

    def build_plan(**kwargs: Any) -> CommandPlan:
        kwargs["cli_version"] = cli_version
        return _codex_command_plan(**kwargs)

    result = run_adapter_local_builder(
        repo_root,
        task_path=task_path,
        adapter=adapter,
        config=CODEX_RUN_CONFIG,
        evaluate_gates=evaluate_local_builder_gates,
        build_command_plan=build_plan,
        prepare_environment=_codex_prepare_environment,
        resolve_executable=resolve_codex_executable,
        base_sha=base_sha,
        agent_executable=codex_executable,
        subprocess_runner=subprocess_runner,
        skip_agent_subprocess=skip_codex,
        fake_agent_exit=fake_codex_exit,
    )
    return LocalBuilderResult(
        run_id=result.run_id,
        task_id=result.task_id,
        status=result.status,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        worktree_path=result.worktree_path,
        allocation_id=result.allocation_id,
        handoff_path=result.handoff_path,
        blocked_reasons=result.blocked_reasons,
        changed_files=result.changed_files,
        verification_results=result.verification_results,
        run_dir=result.run_dir,
        codex_subprocess_invoked=result.agent_subprocess_invoked,
    )