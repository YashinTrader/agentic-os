"""Headless Claude Code reviewer adapter (logical orchestrator process).

Execution layer: launches Claude CLI with restricted tools.
Does not mutate assignment channel state — the supervisor applies validated verdicts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from orchestrator.agent_launcher import LaunchHandle, LaunchPlan, launch_process, probe_version, redact_argv, resolve_executable
from orchestrator.review_schema import REVIEW_JSON_SCHEMA, parse_review_stdout, schema_json_string
from orchestrator.runtime_store import utc_now

AUTH_MODE_LOCAL = "claude_code_local_auth"
AUTH_MODE_API = "anthropic_api"

ALLOWED_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    # Narrow Bash patterns only — reviewed by permission-mode dontAsk.
    "Bash(git status *)",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(git show *)",
    "Bash(git rev-parse *)",
    "Bash(git merge-base *)",
    "Bash(git ls-remote *)",
    "Bash(python -m unittest *)",
    "Bash(python scripts/validate.py *)",
    "Bash(python scripts/handoff_closeout_gate.py *)",
    "Bash(python scripts/verify_repository_verification.py *)",
)

DISALLOWED_TOOLS = (
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "WebSearch",
    "WebFetch",
    "Bash(git push *)",
    "Bash(git merge *)",
    "Bash(git rebase *)",
    "Bash(gh *)",
    "Bash(rm *)",
    "Bash(curl *)",
    "Bash(wget *)",
)

UNSAFE_FLAGS = frozenset(
    {
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--permission-mode=bypassPermissions",
        "bypassPermissions",
    }
)

STATE_QUEUED = "queued"
STATE_LAUNCHING = "launching"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_BLOCKED_AUTH = "blocked_authentication"
STATE_BLOCKED_QUOTA = "blocked_quota"
STATE_BLOCKED_NO_ADAPTER = "blocked_no_adapter"
STATE_BLOCKED_CAPACITY = "blocked_capacity"
STATE_FAILED_LAUNCH = "failed_launch"
STATE_INVALID_OUTPUT = "invalid_structured_output"
STATE_REVIEW_FAILED = "review_failed"
STATE_TIMED_OUT = "timed_out"

SubprocessPopen = Callable[..., Any]


@dataclass
class ReviewRequest:
    assignment_id: str
    task_id: str
    branch: str
    local_sha: str
    remote_sha: str
    handoff_path: str
    base_branch: str = ""
    base_sha: str = ""
    context_bundle_path: str = ""
    prompt_path: str = ""
    resume_session_id: str | None = None
    review_run_id: str = ""
    auth_mode: str = AUTH_MODE_LOCAL
    timeout_seconds: int = 1800
    cwd: str = ""


@dataclass
class ReviewRunState:
    review_run_id: str
    assignment_id: str
    task_id: str
    process_state: str = STATE_QUEUED
    pid: int | None = None
    session_id: str | None = None
    auth_mode: str = AUTH_MODE_LOCAL
    executable: str = ""
    executable_version: str = ""
    command_redacted: list[str] = field(default_factory=list)
    started_at: str | None = None
    heartbeat_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    stdout_path: str = ""
    stderr_path: str = ""
    blocked_reason: str = ""
    verdict: dict[str, Any] | None = None
    retry_count: int = 0
    failure_fingerprint: dict[str, Any] | None = None
    kind: str = "claude_review"
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reviews_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "dispatch" / "reviews"


def review_run_dir(repo_root: Path, review_run_id: str) -> Path:
    path = reviews_dir(repo_root) / review_run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_review_state(repo_root: Path, state: ReviewRunState) -> Path:
    path = review_run_dir(repo_root, state.review_run_id) / "review_run.json"
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_review_state(repo_root: Path, review_run_id: str) -> ReviewRunState | None:
    path = review_run_dir(repo_root, review_run_id) / "review_run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    known = {f.name for f in ReviewRunState.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in data.items() if k in known}
    try:
        return ReviewRunState(**filtered)
    except TypeError:
        return None


def build_reviewer_prompt(*, request: ReviewRequest, context_text: str) -> str:
    return f"""You are the independent chief reviewer and logical orchestrator for Agentic OS.

RULES:
- Do NOT implement, edit, fix, or write code.
- Do NOT merge, push, deploy, or mutate assignment channel files.
- Do NOT approve solely from the handoff summary — inspect the repository yourself.
- Verify actual branch, local SHA, and remote SHA.
- Inspect the actual git diff and changed-file scope.
- Run only permitted tests and gates via allowed tools.
- Distinguish focused tests from full-suite verification.
- Identify stale or fabricated evidence.
- Check security and execution boundaries.
- Return ONLY JSON matching the provided JSON schema (no prose outside JSON).

ASSIGNMENT: {request.assignment_id}
TASK: {request.task_id}
BRANCH: {request.branch}
LOCAL_SHA: {request.local_sha}
REMOTE_SHA: {request.remote_sha}
HANDOFF: {request.handoff_path}
BASE: {request.base_branch} @ {request.base_sha}

CONTEXT BUNDLE:
{context_text}
"""


def build_claude_review_plan(
    *,
    request: ReviewRequest,
    prompt: str,
    claude_executable: str | None = None,
    version_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> LaunchPlan:
    executable = resolve_executable("claude", claude_executable)
    if not executable:
        return LaunchPlan(
            agent="claude-reviewer",
            adapter="claude-reviewer",
            argv=[],
            cwd=request.cwd or ".",
            executable="",
            blocked_reasons=[STATE_BLOCKED_NO_ADAPTER + ": claude executable not found on PATH"],
        )

    # Prefer .cmd on Windows npm shim resolution via which.
    version = probe_version(executable, runner=version_runner)
    argv = [
        executable,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        schema_json_string(),
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        ",".join(ALLOWED_TOOLS),
        "--disallowedTools",
        ",".join(DISALLOWED_TOOLS),
    ]
    if request.resume_session_id:
        argv.extend(["--resume", request.resume_session_id])
    # Never --continue (wrong-session risk). Never skip permissions.

    for flag in argv:
        if flag in UNSAFE_FLAGS or any(u in flag for u in UNSAFE_FLAGS):
            return LaunchPlan(
                agent="claude-reviewer",
                adapter="claude-reviewer",
                argv=[],
                cwd=request.cwd or ".",
                executable=executable,
                blocked_reasons=[f"refusing unsafe claude flag: {flag}"],
            )

    env: dict[str, str] = {}
    if request.auth_mode == AUTH_MODE_API:
        # Key is read only from environment at launch; never serialized into run state.
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return LaunchPlan(
                agent="claude-reviewer",
                adapter="claude-reviewer",
                argv=[],
                cwd=request.cwd or ".",
                executable=executable,
                blocked_reasons=[STATE_BLOCKED_AUTH + ": ANTHROPIC_API_KEY missing for anthropic_api mode"],
            )

    return LaunchPlan(
        agent="claude-reviewer",
        adapter="claude-reviewer",
        argv=argv,
        cwd=request.cwd or ".",
        executable=executable,
        executable_version=version,
        env=env,
        command_redacted=redact_argv(argv),
    )


def classify_reviewer_failure(
    *,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    timed_out: bool,
    launch_error: str | None = None,
) -> tuple[str, str]:
    if launch_error:
        if "blocked_no_adapter" in launch_error:
            return STATE_BLOCKED_NO_ADAPTER, launch_error
        if "blocked_authentication" in launch_error or "auth" in launch_error.lower():
            return STATE_BLOCKED_AUTH, launch_error
        return STATE_FAILED_LAUNCH, launch_error
    if timed_out:
        return STATE_TIMED_OUT, "claude review exceeded timeout"
    blob = f"{stdout}\n{stderr}"
    if re.search(r"401|oauth|not logged in|unauthori[sz]ed|token has been revoked|authentication", blob, re.I):
        return STATE_BLOCKED_AUTH, "authentication failure in Claude CLI output"
    if re.search(r"quota|rate[\s_-]?limit|usage[\s_-]?limit|\b429\b", blob, re.I):
        return STATE_BLOCKED_QUOTA, "quota/rate limit failure in Claude CLI output"
    if exit_code not in (0, None):
        return STATE_REVIEW_FAILED, f"claude exit code {exit_code}"
    return STATE_COMPLETED, "ok"


def extract_claude_session_id(stdout: str, stderr: str = "") -> str | None:
    blob = f"{stdout}\n{stderr}"
    for pattern in (
        re.compile(r'"session_id"\s*:\s*"([^"]+)"', re.I),
        re.compile(r'"sessionId"\s*:\s*"([^"]+)"'),
    ):
        match = pattern.search(blob)
        if match:
            return match.group(1)
    return None


class ClaudeReviewerAdapter:
    """Adapter interface: launch_review / poll_review / collect_verdict / cancel_review."""

    def __init__(
        self,
        repo_root: Path,
        *,
        claude_executable: str | None = None,
        auth_mode: str = AUTH_MODE_LOCAL,
        popen: SubprocessPopen | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.claude_executable = claude_executable
        self.auth_mode = auth_mode
        self.popen = popen
        self._handles: dict[str, LaunchHandle] = {}

    def launch_review(self, request: ReviewRequest) -> ReviewRunState:
        run_id = request.review_run_id or f"review-{request.assignment_id}"
        request.review_run_id = run_id
        cwd = request.cwd or str(self.repo_root)
        request.cwd = cwd
        request.auth_mode = self.auth_mode

        context_text = ""
        if request.context_bundle_path:
            p = Path(request.context_bundle_path)
            if p.is_file():
                context_text = p.read_text(encoding="utf-8", errors="replace")[:20000]
        prompt = build_reviewer_prompt(request=request, context_text=context_text)
        if request.prompt_path:
            Path(request.prompt_path).write_text(prompt, encoding="utf-8")

        plan = build_claude_review_plan(
            request=request,
            prompt=prompt,
            claude_executable=self.claude_executable,
        )
        state = ReviewRunState(
            review_run_id=run_id,
            assignment_id=request.assignment_id,
            task_id=request.task_id,
            process_state=STATE_QUEUED,
            auth_mode=self.auth_mode,
            executable=plan.executable,
            executable_version=plan.executable_version,
            command_redacted=list(plan.command_redacted),
            started_at=utc_now(),
        )
        if not plan.ok:
            state.process_state = (
                STATE_BLOCKED_NO_ADAPTER
                if any("blocked_no_adapter" in r for r in plan.blocked_reasons)
                else STATE_BLOCKED_AUTH
                if any("blocked_authentication" in r or "auth" in r.lower() for r in plan.blocked_reasons)
                else STATE_FAILED_LAUNCH
            )
            state.blocked_reason = "; ".join(plan.blocked_reasons)
            state.completed_at = utc_now()
            save_review_state(self.repo_root, state)
            return state

        run_dir = review_run_dir(self.repo_root, run_id)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        state.process_state = STATE_LAUNCHING
        state.stdout_path = stdout_path.relative_to(self.repo_root).as_posix()
        state.stderr_path = stderr_path.relative_to(self.repo_root).as_posix()
        save_review_state(self.repo_root, state)

        handle, msg = launch_process(plan, stdout_path=stdout_path, stderr_path=stderr_path, popen=self.popen)
        if handle is None:
            state.process_state = STATE_FAILED_LAUNCH
            state.blocked_reason = msg
            state.completed_at = utc_now()
            save_review_state(self.repo_root, state)
            return state

        self._handles[run_id] = handle
        state.pid = handle.pid
        state.process_state = STATE_RUNNING
        state.heartbeat_at = utc_now()
        save_review_state(self.repo_root, state)
        return state

    def poll_review(self, run_id: str) -> ReviewRunState:
        state = load_review_state(self.repo_root, run_id)
        if state is None:
            return ReviewRunState(
                review_run_id=run_id,
                assignment_id="",
                task_id="",
                process_state=STATE_REVIEW_FAILED,
                blocked_reason="unknown review run",
            )
        handle = self._handles.get(run_id)
        if handle is None:
            state.heartbeat_at = utc_now()
            save_review_state(self.repo_root, state)
            return state
        code = handle.process.poll()
        state.heartbeat_at = utc_now()
        if code is not None:
            state.exit_code = int(code)
            state.completed_at = utc_now()
            stdout = Path(self.repo_root / state.stdout_path).read_text(encoding="utf-8", errors="replace") if state.stdout_path else ""
            stderr = Path(self.repo_root / state.stderr_path).read_text(encoding="utf-8", errors="replace") if state.stderr_path else ""
            state.session_id = extract_claude_session_id(stdout, stderr)
            fail_state, detail = classify_reviewer_failure(
                exit_code=state.exit_code, stdout=stdout, stderr=stderr, timed_out=False
            )
            if fail_state != STATE_COMPLETED:
                state.process_state = fail_state
                state.blocked_reason = detail
            else:
                verdict, errors = parse_review_stdout(stdout)
                if verdict is None:
                    state.process_state = STATE_INVALID_OUTPUT
                    state.blocked_reason = "; ".join(errors)
                else:
                    state.process_state = STATE_COMPLETED
                    state.verdict = verdict.to_dict()
            save_review_state(self.repo_root, state)
            self._handles.pop(run_id, None)
        else:
            save_review_state(self.repo_root, state)
        return state

    def collect_verdict(self, run_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        state = self.poll_review(run_id)
        if state.process_state != STATE_COMPLETED or not state.verdict:
            return None, [state.blocked_reason or state.process_state]
        return state.verdict, []

    def cancel_review(self, run_id: str) -> ReviewRunState:
        state = load_review_state(self.repo_root, run_id) or ReviewRunState(
            review_run_id=run_id, assignment_id="", task_id=""
        )
        handle = self._handles.get(run_id)
        if handle is not None:
            try:
                handle.process.kill()
            except OSError:
                pass
            self._handles.pop(run_id, None)
        state.process_state = STATE_REVIEW_FAILED
        state.blocked_reason = "cancelled"
        state.completed_at = utc_now()
        save_review_state(self.repo_root, state)
        return state


def claude_available() -> tuple[bool, str, str]:
    """Return (ok, version_or_reason, executable_path). Never returns secrets."""
    exe = shutil.which("claude")
    if not exe:
        return False, "claude not on PATH", ""
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc), exe
    version = (proc.stdout or proc.stderr or "").strip().splitlines()
    return True, (version[0] if version else "unknown"), exe
