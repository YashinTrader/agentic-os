"""Offline Antigravity spike. No registry or scheduled-supervisor integration.

Only execute_experiment may launch; the checked-in config disables that path.
Evidence intentionally contains typed signals rather than arbitrary log messages.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from types import SimpleNamespace

import yaml

from dispatch import work_lock
from dispatch.agent_environment import build_minimal_environment
from orchestrator.agent_launcher import LaunchPlan, launch_process, resolve_executable
from orchestrator.builder_condition import schedule_next_eligible
from orchestrator.failure_classify import Classification, build_fingerprint
from orchestrator.process_ownership import ownership_metadata, terminate_owned
from orchestrator.run_deadlines import RunDeadlines, adapter_deadlines
from orchestrator.runtime_store import utc_now
from root_paths import resolve_config_root

ADAPTER = "antigravity-restricted"
READ_ONLY_ROLES = frozenset({"read-only-analysis"})
DEVELOPMENT_ROLE = "isolated-development-experiment"
ENVIRONMENT = frozenset({"PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "SYSTEMROOT", "PATHEXT"})
GLOG = re.compile(r'^[IWEF]\d{4} \d{2}:\d{2}:\d{2}\.\d{6}\s+\d+ [\w./-]+:\d+\] (.*)$')
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


def redact_email(value: str) -> str:
    return EMAIL.sub("[redacted-email]", value)


@dataclass
class Evidence:
    requested_model: str
    expected_model_label: str
    resolved_model_label: str | None = None
    auth_state: str = "unknown"
    default_resolver_seen: bool = False
    model_confirmed: bool = False
    silent_fallback_detected: bool = False
    conversation_id: str | None = None
    sandbox_applied: bool = False
    mode_applied: str | None = None
    permission_soft_denials: int = 0
    permission_config_warnings: int = 0
    permission_settings_seen: bool = False
    completion_signal: bool = False
    quota_events: int = 0
    quota_exhausted: bool = False
    log_events: int = 0
    token_usage: None = None


def parse_log(log: str, *, requested_model: str, expected_model_label: str) -> Evidence:
    evidence = Evidence(redact_email(requested_model), redact_email(expected_model_label))
    completed = set()
    for line in log.splitlines():
        match = GLOG.fullmatch(line)
        if not match:
            continue
        message = match[1]
        evidence.log_events += 1
        if "not authenticated, trying silent auth" in message:
            evidence.auth_state = "silent_auth_pending"
        if "authenticated via keyring" in message or "silent auth succeeded" in message:
            evidence.auth_state = "authenticated"
        if "not logged into Antigravity" in message or "silent auth failed" in message:
            evidence.auth_state = "authentication_failed"
        if "defaulting to CCPA" in message or "Model resolved via default" in message:
            evidence.default_resolver_seen = True
            evidence.model_confirmed = False
        label = re.search(r'Propagating selected model override to backend: label="([^"]+)"', message)
        if label:
            evidence.resolved_model_label = redact_email(label[1])
            evidence.model_confirmed = label[1] == expected_model_label
        conversation = re.search(rf'(?:Created conversation |Print mode: conversation=)({UUID})', message)
        if conversation:
            evidence.conversation_id = conversation[1]
        if "enabling terminal sandbox for this session" in message:
            evidence.sandbox_applied = True
        mode = re.search(r'applying agent mode (plan|accept-edits)\b', message)
        if mode:
            evidence.mode_applied = mode[1]
        if "CLI settings initialized: permissions=" in message:
            evidence.permission_settings_seen = True
        if 'Invalid "unsandboxed" permission rules found' in message:
            evidence.permission_config_warnings += 1
        # Synthetic fixture vocabulary only; capture real tool denials in Phase 2.
        elif re.search(r'\btool permission denied\b', message, re.I):
            evidence.permission_soft_denials += 1
        if re.search(r'quota|rate limit|\b429\b', message, re.I):
            evidence.quota_events += 1
            # Refresh is liveness, never proof of exhaustion.
            if re.search(r'quota.*(?:exhausted|exceeded)|(?:exhausted|exceeded).*quota|rate limit|\b429\b', message, re.I):
                evidence.quota_exhausted = True
        completion = re.search(rf'Stream goroutine exited for ({UUID}), sending completion signal', message)
        if completion:
            completed.add(completion[1])
    evidence.completion_signal = evidence.conversation_id is not None and evidence.conversation_id in completed
    evidence.silent_fallback_detected = not evidence.model_confirmed and (
        evidence.default_resolver_seen or evidence.resolved_model_label is not None)
    return evidence


def classify(evidence: Evidence, *, exit_code: int | None, deadline_state: str | None = None,
             expected_mode: str = "plan") -> Classification:
    if deadline_state:
        return Classification(deadline_state, "deadline", "owned run deadline expired")
    if evidence.auth_state == "authentication_failed":
        return Classification("blocked_authentication", "blocked_authentication", "Antigravity authentication required")
    if evidence.quota_exhausted:
        return Classification("blocked_quota", "blocked_quota", "Antigravity quota exhausted")
    if not evidence.model_confirmed:
        return Classification("blocked_external", "model_unavailable", "requested backend model label not confirmed")
    if evidence.permission_soft_denials:
        return Classification("blocked_external", "permission_denied", "CLI reported a permission soft-denial")
    if not evidence.sandbox_applied or evidence.mode_applied != expected_mode:
        return Classification("blocked_external", "permission_denied", "sandbox/mode application not confirmed")
    if exit_code == 0 and evidence.completion_signal:
        return Classification("completed", "completed", "candidate success; independent verification required")
    return Classification("failed", "failed", "missing completion signal or nonzero/unknown exit")


def condition_retry_metadata(classification: Classification, *, now, attempts: int = 0) -> dict:
    """Export to the existing condition schedule; never retry within this adapter.

    Model availability requires explicit re-evaluation, since the current scheduler
    supports auth/quota only. Do not disguise it as quota to force a retry.
    """
    if classification.category not in {"blocked_authentication", "blocked_quota"}:
        return {}
    kind = "auth" if classification.category == "blocked_authentication" else "quota"
    return {"blocked_on": f"{kind}:antigravity", "next_eligible_at":
            schedule_next_eligible(now, attempts, classification.retry_after).isoformat()}


def build_launch_plan(*, worktree: Path, run_dir: Path, prompt: str, model: str,
                      role: str, deadline_seconds: int = 300) -> LaunchPlan:
    worktree, run_dir = worktree.resolve(), run_dir.resolve()
    if not worktree.is_dir() or not (worktree / ".git").exists():
        raise ValueError("isolated git worktree/clone required")
    if run_dir.is_relative_to(worktree) or worktree.is_relative_to(run_dir):
        raise ValueError("run_dir must be outside and separate from the isolated worktree")
    if role not in READ_ONLY_ROLES | {DEVELOPMENT_ROLE}:
        raise ValueError("role is not allowlisted")
    if not prompt.strip() or not model.strip() or model.startswith("-"):
        raise ValueError("nonempty prompt and explicit model required")
    if type(deadline_seconds) is not int or not 1 <= deadline_seconds <= 1800:
        raise ValueError("deadline must be an integer in 1..1800 seconds")
    mode = "plan" if role in READ_ONLY_ROLES else "accept-edits"
    executable = resolve_executable("agy") or "agy"
    env, _ = build_minimal_environment(allowlist=ENVIRONMENT)
    return LaunchPlan(agent="antigravity", adapter=ADAPTER, executable=executable,
                      argv=[executable, "-p", prompt, "--model", model, "--sandbox",
                            "--print-timeout", f"{deadline_seconds}s", "--log-file", str(run_dir / "agy.log"),
                            "--mode", mode], cwd=str(worktree), env=env, inherit_environment=False,
                      command_redacted=[executable, "-p", "[prompt omitted]", "--model", redact_email(model)],
                      mcp_isolation={"enforced": False, "status": "unverified per-invocation isolation gap"})


def execute_experiment(repo_root: Path, *, task_id: str, run_id: str, worktree: Path,
                       run_dir: Path, prompt: str, model: str, expected_model_label: str,
                       role: str, deadline_seconds: int = 300, popen=None) -> dict:
    """Guarded future experiment entry point; production config always refuses.

    popen injection is for offline tests. All real children use the shared Job path.
    Durable work ownership is retained for independent review, including on failure.
    """
    config_path = resolve_config_root(repo_root) / "agents/antigravity_restricted_adapter.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("enabled") is not True or config.get("supports_execution") is not True:
        raise PermissionError("Antigravity experimental adapter is disabled")
    worktree, run_dir = worktree.resolve(), run_dir.resolve()
    if not expected_model_label.strip():
        raise ValueError("independently established model label required")
    if worktree.resolve() == repo_root.resolve():
        raise ValueError("execution requires a separate isolated worktree")
    plan = build_launch_plan(worktree=worktree, run_dir=run_dir, prompt=prompt, model=model,
                             role=role, deadline_seconds=deadline_seconds)
    policy = adapter_deadlines(repo_root, ADAPTER, deadline_seconds)
    if run_dir.exists():
        raise ValueError("run_dir must be fresh; previous log evidence cannot be reused")
    work_lock.acquire(repo_root, task_id, holder_agent="antigravity", route=ADAPTER, run_id=run_id)
    process = None
    try:
        handle, error = launch_process(plan, stdout_path=run_dir / "stdout.txt",
                                       stderr_path=run_dir / "stderr.txt", popen=popen)
        if handle is None:
            return {"classification": asdict(Classification("failed_launch", "failed_launch", "owned launch failed"))}
        process = handle.process
        deadlines = RunDeadlines(policy, handle.started_monotonic)
        activity = SimpleNamespace(startup_activity_at=None, last_activity_at=None, activity_events=0)
        previous_events = 0
        deadline_state = None
        log_path = run_dir / "agy.log"
        while True:
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            evidence = parse_log(log, requested_model=model, expected_model_label=expected_model_label)
            clock = time.monotonic()
            if evidence.log_events > previous_events:
                deadlines.activity(clock, activity, utc_now(), evidence.log_events - previous_events)
                previous_events = evidence.log_events
            expired = deadlines.expired(clock)
            if expired:
                deadline_state = expired[1]
                terminate_owned(process)
                process.wait(timeout=5)
                break
            if process.poll() is not None:
                # Read once more after exit to include the final flushed signal.
                log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
                evidence = parse_log(log, requested_model=model, expected_model_label=expected_model_label)
                break
            work_lock.heartbeat(repo_root, task_id, run_id=run_id)
            time.sleep(0.1)
        result = classify(evidence, exit_code=process.returncode, deadline_state=deadline_state,
                          expected_mode="plan" if role in READ_ONLY_ROLES else "accept-edits")
        return {"classification": asdict(result), "evidence": asdict(evidence),
                "ownership": ownership_metadata(process), "independent_verification_required": True,
                "condition_retry": condition_retry_metadata(result, now=datetime.now(timezone.utc)),
                "failure_fingerprint": asdict(build_fingerprint(agent="antigravity", adapter=ADAPTER,
                        classification=result, exit_code=process.returncode))}
    finally:
        if process is not None:
            # Also close descendants remaining after a normal root exit.
            terminate_owned(process)
        work_lock.heartbeat(repo_root, task_id, run_id=run_id, state="awaiting_review")
