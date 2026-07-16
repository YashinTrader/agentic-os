"""Physical agent process launchers (Grok primary, Codex fallback)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from orchestrator.runtime_store import STATE_BLOCKED_NO_ADAPTER, STATE_FAILED_LAUNCH, STATE_LAUNCHING

SubprocessPopen = Callable[..., Any]

UNSAFE_GROK_FLAGS = frozenset(
    {
        "--always-approve",
        "--permission-mode=bypassPermissions",
        "bypassPermissions",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--dangerously-bypass-approvals",
    }
)

SECRET_FLAG_RE = re.compile(r"(api[_-]?key|token|password|secret|authorization)=?\S*", re.I)


@dataclass
class LaunchPlan:
    agent: str
    adapter: str
    argv: list[str]
    cwd: str
    executable: str
    executable_version: str = ""
    env: dict[str, str] = field(default_factory=dict)
    blocked_reasons: list[str] = field(default_factory=list)
    command_redacted: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocked_reasons and bool(self.argv)


@dataclass
class LaunchHandle:
    process: Any
    pid: int
    session_id: str | None
    stdout_path: Path
    stderr_path: Path
    argv: list[str]
    command_redacted: list[str]
    executable: str
    executable_version: str
    cwd: str


def redact_argv(argv: Sequence[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for item in argv:
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        lower = item.lower()
        if lower in {"--api-key", "--token", "--password", "--secret"}:
            redacted.append(item)
            hide_next = True
            continue
        redacted.append(SECRET_FLAG_RE.sub(lambda m: m.group(0).split("=")[0] + "=***", item))
    return redacted


def resolve_executable(name: str, explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        found = shutil.which(explicit)
        if found:
            return found
        # Allow dry-plan / test argv construction with an explicit path that is
        # not installed on this host.
        if any(sep in explicit for sep in ("/", "\\")) or explicit.lower().endswith(
            (".exe", ".bat", ".cmd", ".ps1")
        ):
            return explicit
    return shutil.which(name)


def probe_version(executable: str, *, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> str:
    run = runner or subprocess.run
    try:
        proc = run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0][:120] if text else "unknown"


def build_grok_launch_plan(
    *,
    worktree: Path,
    prompt: str,
    max_turns: int = 30,
    timeout_hint_seconds: int = 1800,
    grok_executable: str | None = None,
    output_format: str = "json",
    version_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> LaunchPlan:
    del timeout_hint_seconds  # bounded by process monitor, not argv
    executable = resolve_executable("grok", grok_executable)
    if not executable:
        return LaunchPlan(
            agent="composer",
            adapter="composer-restricted",
            argv=[],
            cwd=str(worktree),
            executable="",
            blocked_reasons=[STATE_BLOCKED_NO_ADAPTER + ": grok executable not found on PATH"],
        )

    if max_turns < 1 or max_turns > 200:
        return LaunchPlan(
            agent="composer",
            adapter="composer-restricted",
            argv=[],
            cwd=str(worktree),
            executable=executable,
            blocked_reasons=["max_turns out of safe bounds (1..200)"],
        )

    # Prefer non-interactive single-task form supported by Grok Build 0.2.x:
    #   grok --cwd <dir> --max-turns N --output-format json --single "<prompt>"
    argv = [
        executable,
        "--cwd",
        str(worktree),
        "--max-turns",
        str(max_turns),
        "--output-format",
        output_format,
        "--single",
        prompt,
    ]
    for flag in argv:
        if flag in UNSAFE_GROK_FLAGS or any(u in flag for u in UNSAFE_GROK_FLAGS):
            return LaunchPlan(
                agent="composer",
                adapter="composer-restricted",
                argv=[],
                cwd=str(worktree),
                executable=executable,
                blocked_reasons=[f"refusing unsafe grok flag: {flag}"],
            )

    version = probe_version(executable, runner=version_runner)
    return LaunchPlan(
        agent="composer",
        adapter="composer-restricted",
        argv=argv,
        cwd=str(worktree),
        executable=executable,
        executable_version=version,
        env={},
        command_redacted=redact_argv(argv),
    )


def build_codex_fallback_plan(
    *,
    repo_root: Path,
    worktree: Path,
    task_path: Path,
    agent_output_path: Path,
    codex_executable: str | None = None,
) -> LaunchPlan:
    """Expose existing Codex local-builder command construction behind launcher interface."""
    try:
        from dispatch.codex_adapter import (
            build_codex_command,
            load_codex_restricted_adapter,
            resolve_codex_executable,
        )
    except Exception as exc:  # pragma: no cover - import surface
        return LaunchPlan(
            agent="codex",
            adapter="codex-restricted",
            argv=[],
            cwd=str(worktree),
            executable="",
            blocked_reasons=[f"{STATE_BLOCKED_NO_ADAPTER}: codex adapter unavailable: {exc}"],
        )

    adapter = load_codex_restricted_adapter(repo_root)
    executable = resolve_codex_executable(codex_executable)
    if not executable:
        return LaunchPlan(
            agent="codex",
            adapter="codex-restricted",
            argv=[],
            cwd=str(worktree),
            executable="",
            blocked_reasons=[STATE_BLOCKED_NO_ADAPTER + ": codex executable not found"],
        )
    run_id = f"codex-fallback-{worktree.name}"
    stdout_path = str(agent_output_path.with_name("codex_stdout.log"))
    stderr_path = str(agent_output_path.with_name("codex_stderr.log"))
    plan = build_codex_command(
        adapter,
        repo_root=repo_root,
        worktree_path=str(worktree),
        run_id=run_id,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        agent_output_path=str(agent_output_path),
        timeout_seconds=int(adapter.get("timeout_seconds") or 1800),
        prompt=f"Execute assignment task from {task_path.as_posix()} in this isolated worktree.",
    )
    if plan.blocked_reasons:
        return LaunchPlan(
            agent="codex",
            adapter="codex-restricted",
            argv=[],
            cwd=str(worktree),
            executable=executable,
            blocked_reasons=list(plan.blocked_reasons),
        )
    return LaunchPlan(
        agent="codex",
        adapter="codex-restricted",
        argv=list(plan.argv),
        cwd=plan.cwd,
        executable=executable,
        executable_version=probe_version(executable),
        command_redacted=redact_argv(plan.argv),
    )


def launch_process(
    plan: LaunchPlan,
    *,
    stdout_path: Path,
    stderr_path: Path,
    popen: SubprocessPopen | None = None,
    session_id: str | None = None,
) -> tuple[LaunchHandle | None, str]:
    if not plan.ok:
        reason = "; ".join(plan.blocked_reasons) or STATE_FAILED_LAUNCH
        return None, reason

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_f = stdout_path.open("w", encoding="utf-8")
    stderr_f = stderr_path.open("w", encoding="utf-8")
    runner = popen or subprocess.Popen
    try:
        proc = runner(
            plan.argv,
            cwd=plan.cwd,
            stdout=stdout_f,
            stderr=stderr_f,
            shell=False,
            env={**os.environ, **plan.env} if plan.env else None,
            text=True,
        )
    except OSError as exc:
        stdout_f.close()
        stderr_f.close()
        return None, f"{STATE_FAILED_LAUNCH}: {exc}"

    # File handles owned by process; close our copies after handoff on platforms that dup.
    try:
        stdout_f.close()
        stderr_f.close()
    except OSError:
        pass

    pid = int(getattr(proc, "pid", 0) or 0)
    if pid <= 0:
        return None, f"{STATE_FAILED_LAUNCH}: process started without PID"

    return (
        LaunchHandle(
            process=proc,
            pid=pid,
            session_id=session_id,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            argv=list(plan.argv),
            command_redacted=list(plan.command_redacted),
            executable=plan.executable,
            executable_version=plan.executable_version,
            cwd=plan.cwd,
        ),
        STATE_LAUNCHING,
    )


def extract_session_id(stdout_text: str, stderr_text: str = "") -> str | None:
    blob = f"{stdout_text}\n{stderr_text}"
    patterns = (
        re.compile(r'"session_id"\s*:\s*"([^"]+)"', re.I),
        re.compile(r'"sessionId"\s*:\s*"([^"]+)"'),
        re.compile(r"session[_ -]?id[:\s]+([0-9a-fA-F-]{8,})", re.I),
    )
    for pattern in patterns:
        match = pattern.search(blob)
        if match:
            return match.group(1)
    return None
