"""Bounded, opt-in paid quota recovery. No caller may probe without blocked runs."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from dispatch.atomic_io import atomic_write_json
from dispatch.work_lock import WorkLockError, _guard
from orchestrator.agent_launcher import resolve_executable
from orchestrator.process_ownership import owned_popen, terminate_owned

PROVIDERS = ("codex", "grok", "claude")
PROMPT = "Reply with exactly: ok"


def load_config(root: Path) -> dict[str, Any]:
    path = root / "agents" / "quota_probe.yaml"
    if not path.exists():
        return {"enabled": False, "min_interval_seconds": 3600}
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("quota_probe config must be a mapping")
    interval = config.get("min_interval_seconds", 3600)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError("min_interval_seconds must be a positive integer")
    if interval < 3600 and config.get("owner_override") is not True:
        raise ValueError("paid probes require >= 3600 seconds or explicit owner_override: true")
    if not isinstance(config.get("enabled", False), bool):
        raise ValueError("quota_probe enabled must be boolean")
    if config.get("enabled") and not isinstance(config.get("codex_model"), str):
        raise ValueError("configure a cheapest codex_model for paid probes")
    if config.get("enabled") and not config["codex_model"].strip():
        raise ValueError("codex_model must not be empty")
    return {**config, "min_interval_seconds": interval}


def ledger_path(root: Path) -> Path:
    return root / "runtime/dispatch/paid_quota_probes.json"


def evidence_path(root: Path) -> Path:
    return root / "runtime/dispatch/paid_quota_probes.jsonl"


def _read_ledger(root: Path) -> dict:
    path = ledger_path(root)
    if not path.exists():
        return {}
    # Fail closed: corrupt rate-limit state must never grant another paid call.
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(ledger, dict) or not all(isinstance(v, dict) for v in ledger.values()):
        raise ValueError("invalid paid probe ledger")
    return ledger


def _append(root: Path, row: dict) -> None:
    path = evidence_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _classify(provider: str, stdout: str, stderr: str, code: int | None) -> dict:
    blob = stdout + "\n" + stderr
    misconfigured = re.search(
        r"model[^\n]*not supported|unsupported[\s_-]+model|invalid[\s_-]+request|"
        r"unknown[\s_-]+model|auth[\s_-]*plan[\s_-]*mismatch|"
        r"model[^\n]*(?:ChatGPT account|not available.*(?:plan|account))",
        blob, re.I,
    )
    if misconfigured:
        classification = "probe_misconfigured"
    elif re.search(r"usage[\s_-]?limit|quota|rate[\s_-]?limit|\b40[2]\b|\b429\b|balance|too many requests", blob, re.I):
        classification = "blocked_quota"
    elif re.search(r"turn\.failed", blob):
        classification = "turn_failed"
    elif code != 0:
        classification = "nonzero_exit"
    else:
        events = []
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        if provider == "codex":
            success = any(isinstance(e, dict) and (
                e.get("type") == "turn.completed" or (
                    e.get("type") == "item.completed" and
                    isinstance(e.get("item"), dict) and
                    e["item"].get("type") == "agent_message" and
                    str(e["item"].get("text", "")).strip() == "ok"
                )) for e in events)
        elif provider == "grok":
            try:
                events = [json.loads(stdout)]
            except ValueError:
                pass
            success = bool(events) and all(isinstance(e, dict) and not (
                e.get("is_error") or e.get("error") or
                e.get("type") == "error" or e.get("status") == "error"
            ) for e in events) and any(e.get("result") for e in events if isinstance(e, dict))
        else:
            success = stdout.strip() == "ok"
        classification = "completed" if success else "invalid_result"
    result = {"outcome": "success" if classification == "completed" else "failure",
              "exit_code": code, "classification": classification}
    if classification == "probe_misconfigured":
        result["reason"] = "Probe model/request is unsupported or incompatible with the account plan"
    return result


def run_quota_probe(provider: str, *, config: dict) -> dict:
    """Launch a resolved CLI in an empty cwd, with closed stdin and an owned tree."""
    executable = resolve_executable(provider)
    if not executable:
        return {"outcome": "failure", "exit_code": None, "classification": "executable_missing"}
    with tempfile.TemporaryDirectory(prefix="agentic-quota-") as directory:
        if provider == "codex":
            argv = [executable, "exec", "-m", config["codex_model"],
                    "-c", "model_reasoning_effort=low", "-c", "mcp_servers={}",
                    "-s", "read-only", "--skip-git-repo-check", "--json", PROMPT]
        elif provider == "grok":
            argv = [executable, "--cwd", directory, "--max-turns", "1",
                    "--output-format", "json", "--single", PROMPT]
        elif provider == "claude":
            argv = [executable, "-p", PROMPT, "--model", "haiku"]
        else:
            raise ValueError("unsupported quota provider")
        process = None
        try:
            process = owned_popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                  errors="replace", cwd=directory, shell=False)
            stdout, stderr = process.communicate(timeout=120)
            return _classify(provider, stdout, stderr, process.returncode)
        except subprocess.TimeoutExpired:
            return {"outcome": "failure", "exit_code": None, "classification": "timed_out"}
        except (OSError, subprocess.SubprocessError):
            return {"outcome": "failure", "exit_code": None, "classification": "launch_error"}
        finally:
            if process is not None:
                # Also kill descendants left behind by an exited root.
                terminate_owned(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


def probe_blocked_providers(root: Path, states: list, *, now: datetime) -> set[str]:
    from orchestrator.builder_condition import parse_time

    blocked = {s.blocked_on.partition(":")[2] for s in states
               if s.blocked_on.startswith("quota:") and not s.condition_retry_dispatched_at
               and not s.escalated_at}
    if not blocked:
        return set()
    config = load_config(root)
    if not config.get("enabled"):
        return set()
    cleared = set()
    batch_start = time.monotonic()
    for provider in sorted(blocked.intersection(PROVIDERS)):
        try:
            with _guard(ledger_path(root)):
                # Earlier providers may have spent 120s in this tick. Preserve
                # subsecond precision and account for that delay when reserving.
                started = now + timedelta(seconds=time.monotonic() - batch_start)
                started_at = started.isoformat().replace("+00:00", "Z")
                row = dict(provider=provider, started_at=started_at, duration=0,
                           outcome="started", exit_code=None, classification="pending")
                ledger = _read_ledger(root)
                entry = ledger.get(provider, {})
                last = entry.get("last_paid_probe_at")
                if entry and not last:
                    raise ValueError("missing last_paid_probe_at")
                if last and (started - parse_time(last)).total_seconds() < config["min_interval_seconds"]:
                    continue
                # Reserve before execution. A crash spends the window conservatively.
                ledger[provider] = {"last_paid_probe_at": started_at}
                atomic_write_json(ledger_path(root), ledger)
                _append(root, row)
                start = time.monotonic()
                try:
                    result = run_quota_probe(provider, config=config)
                except Exception:
                    result = {"outcome": "failure", "exit_code": None, "classification": "probe_error"}
                # Keep the OS guard through the bounded call so concurrent
                # supervisors cannot interleave append-only evidence records.
                _append(root, {**row, **result, "duration": round(time.monotonic() - start, 3)})
                ledger[provider].update(classification=result["classification"])
                if result["classification"] == "probe_misconfigured":
                    ledger[provider]["alert_reason"] = result.get("reason", "Probe configuration rejected")
                atomic_write_json(ledger_path(root), ledger)
                if result["outcome"] == "success":
                    cleared.add(provider)
        except (WorkLockError, OSError, ValueError, TypeError):
            continue
    return cleared


def paid_probe_status(root: Path, *, now: datetime) -> dict:
    from orchestrator.builder_condition import parse_time

    try:
        ledger = _read_ledger(root)
    except (OSError, ValueError):
        ledger = {}
    status = {provider: {"last_paid_probe_at": ledger.get(provider, {}).get("last_paid_probe_at"),
                         "paid_probes_24h": 0} for provider in PROVIDERS}
    for provider in PROVIDERS:
        entry = ledger.get(provider, {})
        if entry.get("classification") == "probe_misconfigured":
            status[provider]["alert_reason"] = entry.get("alert_reason", "Probe configuration rejected")
    path = evidence_path(root)
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if (row["outcome"] == "started" and row["provider"] in status and
                            now - timedelta(hours=24) < parse_time(row["started_at"]) <= now):
                        status[row["provider"]]["paid_probes_24h"] += 1
                except (ValueError, KeyError, TypeError):
                    continue
    return status
