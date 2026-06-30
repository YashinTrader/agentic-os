from __future__ import annotations

import html
import http.server
import json
import socketserver
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import yaml

# Resolve the repository root relative to this file
ROOT_DIR = Path(__file__).resolve().parents[1]


# ==========================================
# 1. DATA PARSING & PARSER LOGIC (Schema v2)
# ==========================================

def load_all_tasks(root_dir: Path) -> tuple[list[dict], list[str]]:
    """Scan and parse all task YAML files from the repository following Schema v2."""
    tasks = []
    errors = []
    
    # We scan tasks in active/, blocked/, and done/ directories
    for folder in ("active", "blocked", "done"):
        dir_path = root_dir / "tasks" / folder
        if not dir_path.exists():
            continue
            
        # Glob both *.yaml and *.yml
        files = list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml"))
        
        for file_path in files:
            if file_path.name == "EXAMPLE.yaml":
                # Exclude EXAMPLE.yaml template from the Kanban columns
                continue
                
            try:
                content = file_path.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    # Extract fields using the canonical Schema v2 keys
                    task_item = {
                        "id": data.get("id", file_path.stem),
                        "title": data.get("title", "Untitled Task"),
                        "owner": data.get("owner", "unassigned"),
                        "reviewer": data.get("reviewer", "unassigned"),
                        "created_by": data.get("created_by", "unassigned"),
                        "status": data.get("status", "ready"),
                        "phase": data.get("phase", "1.0"),
                        "created_at": data.get("created_at", "N/A"),
                        "updated_at": data.get("updated_at", "N/A"),
                        "priority": data.get("priority", "medium"),
                        "risk_level": data.get("risk_level", "low"),
                        "requires_human_approval": data.get("requires_human_approval", False),
                        "depends_on": data.get("depends_on", []),
                        "blocks": data.get("blocks", []),
                        "labels": data.get("labels", []),
                        "estimated_effort": data.get("estimated_effort", "S"),
                        "related_decisions": data.get("related_decisions", []),
                        
                        # Markdown text blocks
                        "objective": data.get("objective", ""),
                        "context": data.get("context", ""),
                        "goals": data.get("goals", []),
                        "non_goals": data.get("non_goals", []),
                        "inputs": data.get("inputs", []),
                        "outputs": data.get("outputs", []),
                        "constraints": data.get("constraints", []),
                        "acceptance": data.get("acceptance", []),
                        "human_approval_checklist": data.get("human_approval_checklist", []),
                        "notes": data.get("notes", ""),
                        
                        "file_path": file_path.relative_to(root_dir).as_posix()
                    }
                    tasks.append(task_item)
                else:
                    errors.append(f"File {file_path.name} in tasks/{folder} is not a valid YAML mapping.")
            except Exception as e:
                errors.append(f"Failed to parse tasks/{folder}/{file_path.name}: {str(e)}")
                
    # Deduplicate by task ID, prioritizing done or blocked folders
    unique_tasks = {}
    for t in tasks:
        tid = t["id"]
        if tid not in unique_tasks:
            unique_tasks[tid] = t
        else:
            current_path = unique_tasks[tid]["file_path"]
            new_path = t["file_path"]
            if "done" in new_path or "blocked" in new_path:
                unique_tasks[tid] = t
                
    return sorted(list(unique_tasks.values()), key=lambda x: x["id"]), errors


def load_events(root_dir: Path) -> tuple[list[dict], list[str]]:
    """Parse events log from agent-events.jsonl using the real keys (ts, agent, type)."""
    events = []
    errors = []
    log_path = root_dir / "logs" / "agent-events.jsonl"
    if not log_path.exists():
        return [], ["logs/agent-events.jsonl: file does not exist"]
        
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                if isinstance(ev, dict):
                    events.append(ev)
                else:
                    errors.append(f"logs/agent-events.jsonl:{idx}: Event must be a JSON object.")
            except Exception as e:
                errors.append(f"logs/agent-events.jsonl:{idx}: Invalid JSON: {str(e)}")
    except Exception as e:
        errors.append(f"Failed to read logs/agent-events.jsonl: {str(e)}")
        
    return events, errors


def load_handoffs(root_dir: Path) -> list[Path]:
    """Find all handoff Markdown files in handoffs/ (excluding README.md)."""
    handoffs_dir = root_dir / "handoffs"
    if not handoffs_dir.exists():
        return []
    return sorted([p for p in handoffs_dir.glob("*.md") if p.name.lower() != "readme.md"], key=lambda x: x.name)


def load_adrs(root_dir: Path) -> list[Path]:
    """Find all ADR files in decisions/ (matching ADR-*.md)."""
    decisions_dir = root_dir / "decisions"
    if not decisions_dir.exists():
        return []
    return sorted(list(decisions_dir.glob("ADR-*.md")), key=lambda x: x.name)


def load_cli_inventory(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load runtime/registry/cli_inventory.yaml written by the discovery daemon."""
    errors: list[str] = []
    inventory_path = root_dir / "runtime" / "registry" / "cli_inventory.yaml"
    if not inventory_path.exists():
        return None, ["runtime/registry/cli_inventory.yaml: file does not exist"]
    try:
        data = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("runtime/registry/cli_inventory.yaml: root must be a YAML mapping")
            return None, errors
        tools = data.get("tools", [])
        if not isinstance(tools, list):
            errors.append("runtime/registry/cli_inventory.yaml: tools must be a list")
        return data, errors
    except Exception as exc:
        return None, [f"runtime/registry/cli_inventory.yaml: failed to parse: {exc}"]


def load_skills_registry(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load skills/registry.yaml for the Skills dashboard tab."""
    errors: list[str] = []
    registry_path = root_dir / "skills" / "registry.yaml"
    if not registry_path.exists():
        return None, ["skills/registry.yaml: file does not exist"]
    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("skills/registry.yaml: root must be a YAML mapping")
            return None, errors
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            errors.append("skills/registry.yaml: skills must be a list")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"skills/registry.yaml: failed to parse: {exc}"]


def load_teams_registry(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load teams/registry.yaml for the Teams dashboard tab."""
    errors: list[str] = []
    registry_path = root_dir / "teams" / "registry.yaml"
    if not registry_path.exists():
        return None, ["teams/registry.yaml: file does not exist"]
    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("teams/registry.yaml: root must be a YAML mapping")
            return None, errors
        teams = data.get("teams", [])
        if not isinstance(teams, list):
            errors.append("teams/registry.yaml: teams must be a list")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"teams/registry.yaml: failed to parse: {exc}"]


def load_dispatch_latest(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load latest dispatch dry-run preview JSON if present."""
    errors: list[str] = []
    path = root_dir / "runtime" / "dispatch" / "latest_preview.json"
    if not path.exists():
        return None, errors
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("runtime/dispatch/latest_preview.json: root must be a JSON object")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"runtime/dispatch/latest_preview.json: failed to parse: {exc}"]


def load_dispatch_execution_request(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load latest execution request JSON (read-only, Phase 3.2)."""
    errors: list[str] = []
    path = root_dir / "runtime" / "dispatch" / "latest_execution_request.json"
    if not path.exists():
        return None, errors
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("runtime/dispatch/latest_execution_request.json: root must be a JSON object")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"runtime/dispatch/latest_execution_request.json: failed to parse: {exc}"]


def load_dispatch_execution_result(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load latest execution result JSON (read-only, Phase 3.2)."""
    errors: list[str] = []
    path = root_dir / "runtime" / "dispatch" / "latest_result.json"
    if not path.exists():
        return None, errors
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("runtime/dispatch/latest_result.json: root must be a JSON object")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"runtime/dispatch/latest_result.json: failed to parse: {exc}"]


def _load_json_object(path: Path, label: str) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"{label}: failed to parse: {exc}"
    if not isinstance(data, dict):
        return None, f"{label}: root must be a JSON object"
    return data, None


def _infer_run_task_id(run_dir: Path) -> str:
    task_path = run_dir / "task.yaml"
    if not task_path.exists():
        return ""
    try:
        data = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if isinstance(data, dict):
        return str(data.get("id") or "")
    return ""


def _summarize_verification_status(run_dir: Path, result: dict[str, Any]) -> tuple[str, str | None]:
    verification_path = run_dir / "verification_results.json"
    verification, error = _load_json_object(
        verification_path,
        f"runtime/dispatch/runs/{run_dir.name}/verification_results.json",
    )
    if error:
        return "parse_error", error
    if verification is not None:
        commands = verification.get("commands", [])
        if not isinstance(commands, list) or not commands:
            return "not_recorded", None
        if any(isinstance(cmd, dict) and cmd.get("timed_out") for cmd in commands):
            return "timed_out", None
        if all(isinstance(cmd, dict) and cmd.get("exit_code") == 0 for cmd in commands):
            return "passed", None
        return "failed", None

    status = str(result.get("status") or "")
    if status == "completed_verified":
        return "passed", None
    if status == "completed_unverified":
        return "failed", None
    return "not_recorded", None


REVIEW_PENDING_TASK_STATUSES = frozenset({"review", "awaiting_review"})
RUNNING_RUN_STATUSES = frozenset({"in_progress", "running", "started", "claimed"})


def load_local_builder_claims(root_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load active local-builder claim files keyed by task_id (read-only)."""
    claims_root = root_dir / "runtime" / "dispatch" / "local_builder_claims"
    if not claims_root.exists():
        return {}, []
    if not claims_root.is_dir():
        return {}, ["runtime/dispatch/local_builder_claims: path exists but is not a directory"]

    errors: list[str] = []
    claims: dict[str, dict[str, Any]] = {}
    for path in sorted(claims_root.glob("*.json")):
        data, error = _load_json_object(path, f"runtime/dispatch/local_builder_claims/{path.name}")
        if error:
            errors.append(error)
            continue
        if data is None:
            continue
        task_id = str(data.get("task_id") or path.stem)
        claims[task_id] = {
            "task_id": task_id,
            "run_id": str(data.get("run_id") or ""),
            "claimed_at": str(data.get("claimed_at") or ""),
            "claim_path": f"runtime/dispatch/local_builder_claims/{path.name}",
        }
    return claims, errors


def load_task_lifecycle_index(root_dir: Path) -> dict[str, str]:
    """Map task_id -> lifecycle status from tasks/active, blocked, and done."""
    index: dict[str, str] = {}
    for folder in ("active", "blocked", "done"):
        dir_path = root_dir / "tasks" / folder
        if not dir_path.is_dir():
            continue
        for file_path in list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml")):
            if file_path.name == "EXAMPLE.yaml":
                continue
            try:
                data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("id"):
                index[str(data["id"])] = str(data.get("status") or "")
    return index


def derive_run_claim_state(
    run: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    task_lifecycle: dict[str, str],
) -> str:
    """Derive observational claim/lifecycle state for one execution run row."""
    task_id = str(run.get("task_id") or "")
    if not task_id:
        return "unknown"

    claim = claims.get(task_id)
    if claim:
        if str(claim.get("run_id")) == str(run.get("run_id")):
            return "claimed"
        return "claimed_other_run"

    task_status = str(task_lifecycle.get(task_id) or "").lower()
    if task_status in REVIEW_PENDING_TASK_STATUSES:
        return "review_pending"

    run_status = str(run.get("status") or "").lower()
    if run_status in RUNNING_RUN_STATUSES or (run.get("started_at") and not run.get("finished_at")):
        return "running"

    return "released"


def apply_execution_run_filters(
    runs: list[dict[str, Any]],
    *,
    adapter: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    """Filter execution runs by adapter substring and exact run status (case-insensitive)."""
    filtered = runs
    if adapter:
        adapter_lower = adapter.lower()
        filtered = [run for run in filtered if adapter_lower in str(run.get("adapter_id") or "").lower()]
    if status:
        status_lower = status.lower()
        filtered = [run for run in filtered if str(run.get("status") or "").lower() == status_lower]
    return filtered


def load_execution_runs(root_dir: Path, *, limit: int = 50) -> tuple[list[dict[str, Any]], list[str]]:
    """Load recent local-builder runs from runtime/dispatch/runs without side effects."""
    runs_root = root_dir / "runtime" / "dispatch" / "runs"
    if not runs_root.exists():
        return [], []
    if not runs_root.is_dir():
        return [], ["runtime/dispatch/runs: path exists but is not a directory"]

    errors: list[str] = []
    try:
        run_dirs = [p for p in runs_root.iterdir() if p.is_dir()]
    except Exception as exc:
        return [], [f"runtime/dispatch/runs: failed to list directory: {exc}"]

    def run_sort_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name)
        except OSError:
            return (0.0, path.name)

    runs: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs, key=run_sort_key, reverse=True)[:limit]:
        result_path = run_dir / "result.json"
        result, error = _load_json_object(result_path, f"runtime/dispatch/runs/{run_dir.name}/result.json")
        run_errors: list[str] = []
        if error:
            run_errors.append(error)
            errors.append(error)
        if result is None:
            result = {}
            if not result_path.exists():
                run_errors.append(f"runtime/dispatch/runs/{run_dir.name}/result.json: file does not exist")

        allocation, allocation_error = _load_json_object(
            run_dir / "worktree_allocation.json",
            f"runtime/dispatch/runs/{run_dir.name}/worktree_allocation.json",
        )
        if allocation_error:
            run_errors.append(allocation_error)
            errors.append(allocation_error)

        verification_status, verification_error = _summarize_verification_status(run_dir, result)
        if verification_error:
            run_errors.append(verification_error)
            errors.append(verification_error)

        handoff_path = str(result.get("handoff_path") or "")
        handoff_rel = str(result.get("handoff_rel") or "")
        if not handoff_path and handoff_rel:
            handoff_path = handoff_rel
        elif not handoff_path and (run_dir / "handoff.md").exists():
            handoff_path = f"runtime/dispatch/runs/{run_dir.name}/handoff.md"

        worktree_path = str(result.get("worktree_path") or "")
        if not worktree_path and allocation:
            worktree_path = str(allocation.get("worktree_path") or "")

        task_id = str(result.get("task_id") or _infer_run_task_id(run_dir) or "")
        runs.append(
            {
                "run_id": str(result.get("run_id") or run_dir.name),
                "task_id": task_id,
                "adapter_id": str(result.get("adapter_id") or ""),
                "route": str(result.get("route") or result.get("execution_route") or ""),
                "status": str(result.get("status") or "unknown"),
                "started_at": str(result.get("started_at") or ""),
                "finished_at": str(result.get("finished_at") or ""),
                "worktree_path": worktree_path,
                "verification_status": verification_status,
                "blocked_reasons": result.get("blocked_reasons") if isinstance(result.get("blocked_reasons"), list) else [],
                "handoff_path": handoff_path,
                "run_dir": f"runtime/dispatch/runs/{run_dir.name}",
                "errors": run_errors,
            }
        )

    claims, claim_errors = load_local_builder_claims(root_dir)
    errors.extend(claim_errors)
    task_lifecycle = load_task_lifecycle_index(root_dir)
    for run in runs:
        task_id = str(run.get("task_id") or "")
        run["task_lifecycle_status"] = task_lifecycle.get(task_id, "")
        run["claim_state"] = derive_run_claim_state(run, claims, task_lifecycle)
        active_claim = claims.get(task_id)
        run["active_claim_run_id"] = str(active_claim.get("run_id") or "") if active_claim else ""

    return runs, errors


def load_orchestrator_latest(root_dir: Path) -> tuple[dict | None, dict | None, list[str]]:
    """Load latest orchestrator plan and state JSON if present."""
    errors: list[str] = []
    base = root_dir / "runtime" / "orchestrator"
    plan_path = base / "latest_plan.json"
    state_path = base / "latest_state.json"
    plan = state = None
    try:
        import json

        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"failed to read orchestrator latest files: {exc}")
    return plan, state, errors


def load_obsidian_mapping(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load memory/obsidian_mapping.yaml for the Obsidian Sync dashboard tab."""
    errors: list[str] = []
    mapping_path = root_dir / "memory" / "obsidian_mapping.yaml"
    if not mapping_path.exists():
        return None, ["memory/obsidian_mapping.yaml: file does not exist"]
    try:
        data = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("memory/obsidian_mapping.yaml: root must be a YAML mapping")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"memory/obsidian_mapping.yaml: failed to parse: {exc}"]


def load_obsidian_last_sync_report(root_dir: Path, mapping: dict | None) -> tuple[dict | None, list[str]]:
    """Load last sync report from configured vault path when available."""
    errors: list[str] = []
    if not mapping:
        return None, errors
    vault_path = mapping.get("vault_path")
    last_sync_file = mapping.get("last_sync_file")
    if not vault_path or not last_sync_file:
        return None, errors
    try:
        vault_root = str(mapping.get("vault_root_folder", "AgenticOS"))
        report_rel = str(last_sync_file)
        if report_rel.startswith(f"{vault_root}/"):
            report_rel = report_rel[len(vault_root) + 1 :]
        if ".." in Path(report_rel).parts:
            errors.append("last_sync_file must not contain '..' segments")
            return None, errors
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        from integrations.obsidian.vault_writer import safe_join

        report_path = safe_join(
            Path(str(vault_path)).expanduser().resolve(),
            vault_root,
            report_rel,
        )
        if not report_path.exists():
            return None, errors
        import json

        data = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data, errors
        errors.append("last sync report is not a JSON object")
        return None, errors
    except Exception as exc:
        errors.append(f"failed to read last sync report: {exc}")
        return None, errors


def count_obsidian_notes_planned(root_dir: Path) -> int | None:
    """Count notes that a dry-run sync would generate."""
    try:
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        from integrations.obsidian.sync_to_vault import collect_notes

        notes, _ = collect_notes(root_dir)
        return len(notes)
    except Exception:
        return None


def load_roles_registry(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load roles/registry.yaml for the Roles dashboard tab."""
    errors: list[str] = []
    registry_path = root_dir / "roles" / "registry.yaml"
    if not registry_path.exists():
        return None, ["roles/registry.yaml: file does not exist"]
    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("roles/registry.yaml: root must be a YAML mapping")
            return None, errors
        roles = data.get("roles", [])
        if not isinstance(roles, list):
            errors.append("roles/registry.yaml: roles must be a list")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"roles/registry.yaml: failed to parse: {exc}"]


def load_mcps_registry(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load mcps/registry.yaml for the MCPs dashboard tab."""
    errors: list[str] = []
    registry_path = root_dir / "mcps" / "registry.yaml"
    if not registry_path.exists():
        return None, ["mcps/registry.yaml: file does not exist"]
    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("mcps/registry.yaml: root must be a YAML mapping")
            return None, errors
        mcps = data.get("mcps", [])
        if not isinstance(mcps, list):
            errors.append("mcps/registry.yaml: mcps must be a list")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"mcps/registry.yaml: failed to parse: {exc}"]


def load_daemon_status(root_dir: Path) -> tuple[dict | None, list[str]]:
    """Load runtime/status/daemon_status.json written by the discovery daemon."""
    errors: list[str] = []
    status_path = root_dir / "runtime" / "status" / "daemon_status.json"
    if not status_path.exists():
        return None, ["runtime/status/daemon_status.json: file does not exist"]
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("runtime/status/daemon_status.json: root must be a JSON object")
            return None, errors
        return data, errors
    except Exception as exc:
        return None, [f"runtime/status/daemon_status.json: failed to parse: {exc}"]


def get_health_metrics(root_dir: Path) -> dict:
    """Calculate system stats and health information, distinguishing ok, empty, and error states."""
    tasks, task_errors = load_all_tasks(root_dir)
    events, event_errors = load_events(root_dir)
    
    active_count = sum(1 for t in tasks if t["status"] in ("ready", "in_progress", "review"))
    blocked_count = sum(1 for t in tasks if t["status"] == "blocked")
    done_count = sum(1 for t in tasks if t["status"] == "done")
    
    last_event_ts = "N/A"
    if events:
        try:
            sorted_events = sorted(events, key=lambda x: x.get("ts", ""))
            if sorted_events:
                last_event_ts = sorted_events[-1].get("ts", "N/A")
        except Exception:
            pass
            
    # Task surface status: ok, empty, error
    if task_errors:
        tasks_state = "error"
    elif not tasks:
        tasks_state = "empty"
    else:
        tasks_state = "ok"
        
    # Events surface status: ok, empty, error
    if event_errors:
        events_state = "error"
    elif not events:
        events_state = "empty"
    else:
        events_state = "ok"
        
    return {
        "active_count": active_count,
        "blocked_count": blocked_count,
        "done_count": done_count,
        "last_event_ts": last_event_ts,
        "tasks_state": tasks_state,
        "events_state": events_state,
        "task_errors": task_errors,
        "event_errors": event_errors,
    }


# ==========================================
# 1.5 WRITE ACTIONS & INTERACTIVE PERSISTENCE
# ==========================================

def utc_now() -> str:
    """Generate canonical ISO-8601 UTC timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_cli_script(root_dir: Path, script_name: str, args: list[str]) -> str:
    """Run a CLI script in scripts/ using subprocess and return its stdout. Raise ValueError on failure."""
    script_path = ROOT_DIR / "scripts" / script_name
    cmd = [sys.executable, str(script_path), "--root", str(root_dir)] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or f"Script {script_name} failed with return code {result.returncode}."
        raise ValueError(error_msg)
    return result.stdout.strip()


def append_note_event(root_dir: Path, agent: str, task_id: str, text: str) -> None:
    """Append a comment as a 'note' event to logs/agent-events.jsonl by shelling out."""
    run_cli_script(root_dir, "append_log.py", [
        "--agent", agent,
        "--task", task_id,
        "--type", "note",
        "--text", text,
        "--detail", f"commented on task {task_id}: {text[:50]}..."
    ])


def update_task_file(root_dir: Path, task_id: str, status: str, owner: str, reviewer: str, notes: str) -> Path:
    """Update fields of an existing task YAML by shelling out, and log standard events."""
    current_path = None
    for folder in ("active", "done", "blocked"):
        p = root_dir / "tasks" / folder / f"{task_id}.yaml"
        if p.exists():
            current_path = p
            break
            
    if not current_path:
        raise FileNotFoundError(f"Task {task_id} not found.")
        
    content = current_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValueError(f"Task {task_id} is not a valid YAML mapping.")
        
    old_status = data.get("status", "ready")
    old_owner = data.get("owner", "unassigned")
    
    # Construct args for update_task.py
    args = ["--id", task_id]
    if status:
        args += ["--status", status]
    if owner is not None:
        args += ["--owner", owner]
    if reviewer is not None:
        args += ["--reviewer", reviewer]
    if notes is not None:
        args += ["--handoff-notes", notes]
        
    # Execute the CLI script to update task file
    run_cli_script(root_dir, "update_task.py", args)
    
    # Find the newly moved path (since status update might have moved it)
    target_path = None
    for folder in ("active", "done", "blocked"):
        p = root_dir / "tasks" / folder / f"{task_id}.yaml"
        if p.exists():
            target_path = p
            break
            
    if not target_path:
        raise FileNotFoundError(f"Task {task_id} not found after update.")
        
    # Read the updated task status and target folder location
    target_dir = target_path.parent.name
    
    # Log status changed if needed
    if old_status != status:
        event = {
            "ts": utc_now(),
            "agent": "human",
            "type": "status_changed",
            "task_id": task_id,
            "from": old_status,
            "to": status,
            "detail": f"changed status from {old_status} to {status}"
        }
        log_path = root_dir / "logs" / "agent-events.jsonl"
        with log_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
            
    # Log reassign changed if needed
    if old_owner != owner:
        event = {
            "ts": utc_now(),
            "agent": "human",
            "type": "task_assigned",
            "task_id": task_id,
            "from": old_owner,
            "to": owner,
            "detail": f"reassigned task from {old_owner} to {owner}"
        }
        log_path = root_dir / "logs" / "agent-events.jsonl"
        with log_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
            
    return target_path


def create_task_file(
    root_dir: Path, title: str, owner: str, reviewer: str, objective: str,
    context: str, phase: str, priority: str, risk_level: str,
    goals: list[str], acceptance: list[str]
) -> str:
    """Find next sequential T-NNNN ID, create new YAML in tasks/active/ by shelling out, and log task_created."""
    max_id = 0
    for folder in ("active", "done", "blocked"):
        dir_path = root_dir / "tasks" / folder
        if dir_path.exists():
            for p in dir_path.glob("T-*.yaml"):
                try:
                    num = int(p.stem.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
                    
    next_id = f"T-{max_id + 1:04d}"
    
    # Construct args for create_task.py
    args = [
        "--id", next_id,
        "--title", title,
        "--owner", owner,
        "--reviewer", reviewer,
        "--created-by", "human",
        "--phase", phase,
        "--priority", priority,
        "--risk-level", risk_level,
        "--objective", objective,
    ]
    if context:
        args += ["--context", context]
    for g in goals:
        args += ["--goal", g]
    for a in acceptance:
        args += ["--acceptance", a]
        
    # Run the CLI script to create the task
    run_cli_script(root_dir, "create_task.py", args)
    
    # Log task created
    event = {
        "ts": utc_now(),
        "agent": "human",
        "type": "task_created",
        "task_id": next_id,
        "detail": f"created task: {title}"
    }
    log_path = root_dir / "logs" / "agent-events.jsonl"
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
        
    return next_id


# ==========================================
# 2. LOCAL DYNAMIC HTML GENERATION
# ==========================================

ALLOWED_EVENT_TYPES = {
    "task_created",
    "task_assigned",
    "status_changed",
    "handoff_written",
    "reviewed",
    "decision_recorded",
    "blocked",
    "note",
}

def escape(val: Any) -> str:
    """HTML-escape values to prevent injection."""
    if val is None:
        return ""
    return html.escape(str(val))


def detect_adr_status(file_path: Path) -> str:
    """Read the first 10 lines of an ADR file to detect its status case-insensitively."""
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()[:12]
        for line in lines:
            line_lower = line.lower()
            if "status:" in line_lower:
                parts = line.split(":", 1)
                if len(parts) > 1:
                    status_text = parts[1].strip().lower().replace("*", "").replace("`", "")
                    if "accepted" in status_text:
                        return "accepted"
                    elif "proposed" in status_text:
                        return "proposed"
                    elif "rejected" in status_text:
                        return "rejected"
    except Exception:
        pass
    return "unknown"


def generate_dashboard_html(query_params: dict[str, list[str]]) -> str:
    """Generates the entire premium dashboard page dynamically on load."""
    metrics = get_health_metrics(ROOT_DIR)
    tasks, _ = load_all_tasks(ROOT_DIR)
    events, _ = load_events(ROOT_DIR)
    cli_inventory, cli_inventory_errors = load_cli_inventory(ROOT_DIR)
    daemon_status, daemon_status_errors = load_daemon_status(ROOT_DIR)
    skills_registry, skills_registry_errors = load_skills_registry(ROOT_DIR)
    mcps_registry, mcps_registry_errors = load_mcps_registry(ROOT_DIR)
    teams_registry, teams_registry_errors = load_teams_registry(ROOT_DIR)
    roles_registry, roles_registry_errors = load_roles_registry(ROOT_DIR)
    obsidian_mapping, obsidian_mapping_errors = load_obsidian_mapping(ROOT_DIR)
    orchestrator_plan, orchestrator_state, orchestrator_errors = load_orchestrator_latest(ROOT_DIR)
    dispatch_preview, dispatch_preview_errors = load_dispatch_latest(ROOT_DIR)
    dispatch_exec_request, dispatch_exec_request_errors = load_dispatch_execution_request(ROOT_DIR)
    dispatch_exec_result, dispatch_exec_result_errors = load_dispatch_execution_result(ROOT_DIR)
    execution_runs, execution_run_errors = load_execution_runs(ROOT_DIR)
    obsidian_last_sync, obsidian_sync_errors = load_obsidian_last_sync_report(ROOT_DIR, obsidian_mapping)
    obsidian_notes_planned = count_obsidian_notes_planned(ROOT_DIR)
    
    # 1. State extraction
    selected_task_id = query_params.get("task_id", [None])[0]
    filter_agent = query_params.get("agent", [""])[0].strip()
    filter_task = query_params.get("task", [""])[0].strip()
    skill_filter_agent = query_params.get("skill_agent", [""])[0].strip()
    skill_filter_risk = query_params.get("skill_risk", [""])[0].strip()
    skill_filter_approval = query_params.get("skill_approval", [""])[0].strip()
    skill_filter_category = query_params.get("skill_category", [""])[0].strip()
    mcp_filter_agent = query_params.get("mcp_agent", [""])[0].strip()
    mcp_filter_status = query_params.get("mcp_status", [""])[0].strip()
    team_filter_status = query_params.get("team_status", [""])[0].strip()
    team_filter_agent = query_params.get("team_agent", [""])[0].strip()
    team_filter_skill = query_params.get("team_skill", [""])[0].strip()
    role_filter_agent = query_params.get("role_agent", [""])[0].strip()
    role_filter_risk = query_params.get("role_risk", [""])[0].strip()
    role_filter_approval = query_params.get("role_approval", [""])[0].strip()
    role_filter_can_execute = query_params.get("role_can_execute", [""])[0].strip()
    role_filter_can_review = query_params.get("role_can_review", [""])[0].strip()
    run_filter_adapter = query_params.get("run_adapter", [""])[0].strip()
    run_filter_status = query_params.get("run_status", [""])[0].strip()
    execution_runs = apply_execution_run_filters(
        execution_runs,
        adapter=run_filter_adapter,
        status=run_filter_status,
    )
    suggest_task_id = query_params.get("suggest_task", [""])[0].strip()
    read_file_path = query_params.get("read_file", [None])[0]
    success_alert = query_params.get("success", [None])[0]
    error_alert = query_params.get("error", [None])[0]
    
    # Determine default active tab based on parameters
    active_tab = query_params.get("tab", ["kanban"])[0]
    if not query_params.get("tab"):
        if filter_agent or filter_task:
            active_tab = "events"
        elif read_file_path:
            active_tab = "handoffs"
        
    # Health status badges
    def make_health_badge(state: str) -> str:
        if state == "ok":
            return '<span class="status-badge status-ok">✓ OK</span>'
        elif state == "empty":
            return '<span class="status-badge status-empty">⚡ EMPTY</span>'
        else:
            return '<span class="status-badge status-error">✗ ERROR</span>'
            
    # Event filters logic
    filtered_events = events
    if filter_agent:
        filtered_events = [e for e in filtered_events if filter_agent.lower() in str(e.get("agent", "")).lower()]
    if filter_task:
        filtered_events = [e for e in filtered_events if filter_task.lower() in str(e.get("task", "")).lower() or filter_task.lower() in str(e.get("task_id", "")).lower()]
        
    reversed_events = list(reversed(filtered_events))
    showing_events_count = min(30, len(reversed_events))
    
    # HTML compilation
    html_out = []
    html_out.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Agentic OS Kanban Dashboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');
        
        * {
            box-sizing: border-box;
            font-family: 'Outfit', sans-serif;
        }
        
        body {
            margin: 0;
            background-color: #0f172a;
            color: #f1f5f9;
            display: flex;
            min-height: 100vh;
        }
        
        /* Sidebar Layout */
        .sidebar {
            width: 320px;
            background-color: #1e293b;
            border-right: 1px solid rgba(255, 255, 255, 0.05);
            padding: 24px;
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        
        .main-content {
            flex-grow: 1;
            padding: 30px;
            overflow-y: auto;
        }
        
        /* Sidebar Typography & Cards */
        h1 { font-size: 24px; font-weight: 700; margin: 0 0 4px 0; color: #f8fafc; }
        .subtitle { font-size: 11px; color: #64748b; margin-bottom: 24px; text-transform: uppercase; letter-spacing: 1px; }
        
        .sidebar-section {
            margin-bottom: 24px;
        }
        
        .sidebar-section-title {
            font-size: 11px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
            font-weight: 600;
        }
        
        .kpi-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 14px;
            border-radius: 8px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .kpi-title { font-size: 13px; color: #94a3b8; }
        .kpi-value { font-size: 20px; font-weight: 700; color: #f8fafc; }
        
        .status-badge {
            font-size: 10px;
            font-weight: 700;
            padding: 4px 8px;
            border-radius: 4px;
            text-transform: uppercase;
        }
        
        .status-ok { background: rgba(16, 185, 129, 0.1); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.2); }
        .status-empty { background: rgba(245, 158, 11, 0.1); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.2); }
        .status-error { background: rgba(239, 68, 68, 0.1); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.2); }
        
        /* CSS-only Tabs Switcher */
        .tabs-container {
            display: flex;
            flex-direction: column;
        }
        
        .tab-headers {
            display: flex;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            margin-bottom: 24px;
        }
        
        .tab-link {
            padding: 12px 24px;
            color: #94a3b8;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            border-bottom: 2px solid transparent;
            transition: all 0.2s ease;
        }
        
        .tab-link:hover {
            color: #f1f5f9;
        }
        
        .tab-link.active {
            color: #3b82f6;
            border-bottom-color: #3b82f6;
        }
        
        .tab-panel {
            display: none;
        }
        
        .tab-panel.active {
            display: block;
        }
        
        /* Kanban Columns Layout */
        .kanban-board {
            display: grid;
            grid-template-columns: repeat(5, minmax(200px, 1fr));
            gap: 16px;
            align-items: start;
        }
        
        .kanban-column {
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 10px;
            padding: 16px 12px;
            min-height: 520px;
        }
        
        .column-header {
            font-size: 13px;
            font-weight: 600;
            padding: 6px 12px;
            border-radius: 4px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
        }
        
        .col-ready { background: rgba(148, 163, 184, 0.1); color: #94a3b8; border-left: 4px solid #94a3b8; }
        .col-progress { background: rgba(59, 130, 246, 0.1); color: #3b82f6; border-left: 4px solid #3b82f6; }
        .col-review { background: rgba(168, 85, 247, 0.1); color: #a855f7; border-left: 4px solid #a855f7; }
        .col-blocked { background: rgba(239, 68, 68, 0.1); color: #ef4444; border-left: 4px solid #ef4444; }
        .col-done { background: rgba(16, 185, 129, 0.1); color: #10b981; border-left: 4px solid #10b981; }
        
        /* Task Cards */
        .task-card {
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 12px;
            cursor: pointer;
            display: block;
            text-decoration: none;
            color: inherit;
            transition: all 0.2s ease;
        }
        
        .task-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 16px rgba(0,0,0,0.3);
            border-color: rgba(255, 255, 255, 0.15);
        }
        
        .task-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: #64748b;
            margin-bottom: 8px;
        }
        
        .task-id { font-weight: 700; }
        
        .task-priority {
            padding: 2px 6px;
            font-weight: 700;
            border-radius: 3px;
            text-transform: uppercase;
            font-size: 9px;
        }
        .prio-high { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
        .prio-medium { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
        .prio-low { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
        
        .task-title {
            font-size: 13px;
            font-weight: 600;
            color: #f1f5f9;
            margin-bottom: 8px;
            line-height: 1.4;
        }
        
        .task-objective {
            font-size: 11px;
            color: #94a3b8;
            margin-bottom: 12px;
            line-height: 1.4;
        }
        
        .task-card-footer {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: #64748b;
        }
        
        .task-owner {
            background: rgba(255, 255, 255, 0.05);
            padding: 2px 6px;
            border-radius: 10px;
            color: #cbd5e1;
        }
        
        /* Detailed Inspector Panel */
        .inspector-panel {
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 24px;
            margin-top: 30px;
            box-shadow: 0 12px 24px rgba(0,0,0,0.4);
        }
        
        .inspector-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
            margin-top: 16px;
        }
        
        .inspector-section-title {
            font-size: 12px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
            font-weight: 700;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 4px;
        }
        
        .inspector-list {
            padding-left: 20px;
            margin: 0 0 16px 0;
            font-size: 13px;
            color: #cbd5e1;
            line-height: 1.6;
        }
        
        .inspector-meta-row {
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
        }
        
        .inspector-meta-label { color: #94a3b8; }
        .inspector-meta-val { font-weight: 600; color: #f1f5f9; }
        
        /* Event Log list */
        .event-item {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }
        
        .event-header {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #64748b;
            margin-bottom: 6px;
        }
        
        .event-type-warn {
            background: rgba(245, 158, 11, 0.1);
            border-left: 4px solid #f59e0b;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 11px;
            color: #fbbf24;
            margin-bottom: 8px;
        }
        
        /* Handoffs & ADRs List layout */
        .split-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }
        
        .file-list {
            max-height: 500px;
            overflow-y: auto;
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            padding: 10px;
        }
        
        .file-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 14px;
            color: #cbd5e1;
            text-decoration: none;
            border-radius: 6px;
            margin-bottom: 6px;
            font-size: 13px;
            transition: background 0.2s ease;
        }
        
        .file-item:hover {
            background: rgba(255, 255, 255, 0.05);
            color: #f1f5f9;
        }
        
        .file-item.active {
            background: rgba(59, 130, 246, 0.15);
            color: #3b82f6;
            font-weight: 600;
        }
        
        .reader-panel {
            background: rgba(0, 0, 0, 0.15);
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 24px;
            border-radius: 8px;
            max-height: 600px;
            overflow-y: auto;
            font-size: 14px;
            line-height: 1.6;
        }
        
        /* Forms */
        .filter-form {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }
        .filter-input {
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            color: #f1f5f9;
            padding: 8px 12px;
            font-size: 13px;
        }
        .filter-button {
            background: #3b82f6;
            border: none;
            border-radius: 6px;
            color: white;
            padding: 8px 16px;
            font-weight: 600;
            cursor: pointer;
            font-size: 13px;
        }
        .filter-button:hover { background: #2563eb; }
        
        .clear-link {
            align-self: center;
            font-size: 12px;
            color: #64748b;
            text-decoration: none;
        }
        
        .clear-link:hover { color: #94a3b8; }
        
        /* New Interactive Forms Styling */
        .toast-alert {
            padding: 12px 18px;
            border-radius: 8px;
            margin-bottom: 24px;
            font-size: 14px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .toast-success {
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.25);
        }
        
        .toast-error {
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.25);
        }
        
        /* Comments/Discussion styling */
        .comments-container {
            margin-top: 24px;
            background: rgba(0, 0, 0, 0.15);
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.04);
            padding: 16px;
        }
        
        .comment-item {
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            padding: 12px 0;
        }
        
        .comment-item:last-child {
            border-bottom: none;
        }
        
        .comment-meta {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #64748b;
            margin-bottom: 6px;
        }
        
        .comment-author {
            background: rgba(59, 130, 246, 0.1);
            color: #60a5fa;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
        }
        
        .comment-text {
            font-size: 13px;
            color: #e2e8f0;
            line-height: 1.5;
        }
        
        /* Form inputs styling */
        .interactive-form {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-top: 12px;
        }
        
        .form-label {
            font-size: 12px;
            color: #94a3b8;
            font-weight: 600;
            margin-bottom: -6px;
        }
        
        .form-input, .form-select, .form-textarea {
            background: #0f172a;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: #f1f5f9;
            padding: 8px 12px;
            font-size: 13px;
            width: 100%;
            transition: border-color 0.2s;
        }
        
        .form-input:focus, .form-select:focus, .form-textarea:focus {
            border-color: #3b82f6;
            outline: none;
        }
        
        .form-textarea {
            resize: vertical;
            min-height: 80px;
        }
        
        .form-submit-btn {
            background: #3b82f6;
            border: none;
            color: white;
            padding: 10px 16px;
            font-weight: 600;
            font-size: 13px;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .form-submit-btn:hover {
            background: #2563eb;
        }
        
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        
        /* Create Task Page */
        .create-task-container {
            max-width: 800px;
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 12px 24px rgba(0,0,0,0.3);
        }

        .tools-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-top: 16px;
        }

        .tools-table th,
        .tools-table td {
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            vertical-align: top;
        }

        .tools-table th {
            color: #94a3b8;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .tool-available {
            color: #34d399;
            font-weight: 700;
        }

        .tool-missing {
            color: #f87171;
            font-weight: 700;
        }

        .daemon-health-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }

        .daemon-health-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 14px;
        }

        .daemon-health-label {
            font-size: 11px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }

        .daemon-health-value {
            font-size: 18px;
            font-weight: 700;
            color: #f8fafc;
        }
        
    </style>
</head>
<body>
""")
    
    # 2. RENDER SIDEBAR
    html_out.append(f"""
    <div class="sidebar">
        <h1 style="display:flex; align-items:center; gap:8px;">📋 Agentic OS</h1>
        <div class="subtitle">Control Plane Dashboard</div>
        
        <div class="sidebar-section">
            <div class="sidebar-section-title">🏥 System Surfaces Health</div>
            <div class="kpi-card" style="margin-bottom: 8px;">
                <span class="kpi-title">Tasks Directory</span>
                {make_health_badge(metrics["tasks_state"])}
            </div>
            <div class="kpi-card">
                <span class="kpi-title">Events Log</span>
                {make_health_badge(metrics["events_state"])}
            </div>
        </div>
        
        <div class="sidebar-section">
            <div class="sidebar-section-title">📊 Stats Overview</div>
            <div class="kpi-card" style="margin-bottom: 8px;">
                <span class="kpi-title">Active Tasks</span>
                <span class="kpi-value">{metrics["active_count"]}</span>
            </div>
            <div class="kpi-card" style="margin-bottom: 8px;">
                <span class="kpi-title">Blocked Tasks</span>
                <span class="kpi-value">{metrics["blocked_count"]}</span>
            </div>
            <div class="kpi-card">
                <span class="kpi-title">Completed Tasks</span>
                <span class="kpi-value">{metrics["done_count"]}</span>
            </div>
            <div style="font-size: 9px; color: #64748b; text-align: center; margin-top: 10px;">
                Last Event UTC: <br/><b>{escape(metrics["last_event_ts"])}</b>
            </div>
        </div>
        
        <div style="flex-grow: 1;"></div>
        
        <div style="font-size: 10px; color: #475569; text-align: center; border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 12px;">
            Antigravity Dashboard • Phase 3.0 preview
        </div>
    </div>
    """)
    
    # 3. RENDER MAIN PANELS WITH TABS
    html_out.append("""
    <div class="main-content">
    """)
    
    if success_alert:
        html_out.append(f"""
        <div class="toast-alert toast-success">
            <span>✨</span>
            <span>{escape(success_alert)}</span>
        </div>
        """)
    if error_alert:
        html_out.append(f"""
        <div class="toast-alert toast-error">
            <span>⚠️</span>
            <span><b>Error:</b> {escape(error_alert)}</span>
        </div>
        """)
        
    html_out.append(f"""
        <div class="tabs-container">
            <div class="tab-headers">
                <a href="/?tab=kanban" class="tab-link {'active' if active_tab == 'kanban' else ''}">📋 Kanban Board</a>
                <a href="/?tab=create_task" class="tab-link {'active' if active_tab == 'create_task' else ''}">🆕 Create Task</a>
                <a href="/?tab=events" class="tab-link {'active' if active_tab == 'events' else ''}">📜 System Events</a>
                <a href="/?tab=handoffs" class="tab-link {'active' if active_tab == 'handoffs' else ''}">📑 Handoffs & ADRs</a>
                <a href="/?tab=agents_tools" class="tab-link {'active' if active_tab == 'agents_tools' else ''}">🤖 Agents / Tools</a>
                <a href="/?tab=skills" class="tab-link {'active' if active_tab == 'skills' else ''}">🧩 Skills</a>
                <a href="/?tab=mcps" class="tab-link {'active' if active_tab == 'mcps' else ''}">🔌 MCPs</a>
                <a href="/?tab=teams" class="tab-link {'active' if active_tab == 'teams' else ''}">👥 Teams</a>
                <a href="/?tab=roles" class="tab-link {'active' if active_tab == 'roles' else ''}">🎭 Roles</a>
                <a href="/?tab=obsidian" class="tab-link {'active' if active_tab == 'obsidian' else ''}">📓 Obsidian Sync</a>
                <a href="/?tab=orchestrator" class="tab-link {'active' if active_tab == 'orchestrator' else ''}">🧭 Orchestrator</a>
                <a href="/?tab=dispatch" class="tab-link {'active' if active_tab == 'dispatch' else ''}">🚀 Dispatch Preview</a>
                <a href="/?tab=execution_runs" class="tab-link {'active' if active_tab == 'execution_runs' else ''}">Execution Runs</a>
                <a href="/?tab=health" class="tab-link {'active' if active_tab == 'health' else ''}">🏥 Health Panel</a>
            </div>
    """)
    
    # ==========================================
    # TAB PANEL: KANBAN
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'kanban' else ''}">
                <div class="kanban-board">
    """)
    
    # Render Kanban Columns
    statuses = ["ready", "in_progress", "review", "blocked", "done"]
    col_classes = ["col-ready", "col-progress", "col-review", "col-blocked", "col-done"]
    col_names = ["📝 Ready", "⚡ In Progress", "🔍 In Review", "🛑 Blocked", "✅ Completed"]
    
    for idx, status in enumerate(statuses):
        col_tasks = [t for t in tasks if t["status"] == status]
        html_out.append(f"""
                    <div class="kanban-column">
                        <div class="column-header {col_classes[idx]}">
                            <span>{col_names[idx]}</span>
                            <span>{len(col_tasks)}</span>
                        </div>
        """)
        
        for task in col_tasks:
            priority_val = task.get("priority", "medium")
            priority_class = f"prio-{priority_val.lower()}"
            
            # Risk level color badge
            risk_badge = '<span style="color:#34d399; font-weight:700;">LOW</span>'
            if task["risk_level"] == "medium":
                risk_badge = '<span style="color:#fbbf24; font-weight:700;">MED</span>'
            elif task["risk_level"] == "high":
                risk_badge = '<span style="color:#f87171; font-weight:700;">HIGH</span>'
                
            html_out.append(f"""
                        <a href="/?task_id={escape(task['id'])}&tab=kanban" class="task-card">
                            <div class="task-card-header">
                                <span class="task-id">{escape(task['id'])}</span>
                                <span class="task-priority {priority_class}">{escape(priority_val)}</span>
                            </div>
                            <div class="task-title">{escape(task['title'])}</div>
                            <div class="task-objective">{escape(task['objective'][:100])}...</div>
                            <div class="task-card-footer">
                                <span>Risk: {risk_badge}</span>
                                <span class="task-owner">{escape(task['owner'])}</span>
                            </div>
                        </a>
            """)
            
        html_out.append("""
                    </div>
        """)
        
    html_out.append("""
                </div>
    """)
    
    # Detail Inspector for Selected Task
    if selected_task_id:
        selected_task = next((t for t in tasks if t["id"] == selected_task_id), None)
        if selected_task:
            html_out.append(f"""
                <div class="inspector-panel" id="inspector">
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:12px;">
                        <h2 style="margin:0; font-size:20px; color:#f8fafc;">📋 [{escape(selected_task['id'])}] {escape(selected_task['title'])}</h2>
                        <a href="/?tab=kanban" style="text-decoration:none; font-size:24px; color:#64748b; line-height:1;">&times;</a>
                    </div>
                    
                    <div class="inspector-grid">
                        <div>
                            <div class="inspector-section-title">Objective</div>
                            <p style="font-size:14px; line-height:1.6; color:#cbd5e1; margin: 0 0 20px 0;">{escape(selected_task['objective'])}</p>
                            
                            <div class="inspector-section-title">Context / Rationale</div>
                            <p style="font-size:13px; line-height:1.6; color:#94a3b8; margin: 0 0 20px 0; font-style:italic;">{escape(selected_task.get('context', 'No context rationale supplied.'))}</p>
                            
                            <div class="inspector-section-title">Execution Goals</div>
                            <ul class="inspector-list">
            """)
            for goal in selected_task.get("goals", []):
                html_out.append(f"<li>{escape(goal)}</li>")
            if not selected_task.get("goals"):
                html_out.append("<li>None specified.</li>")
                
            html_out.append("""
                            </ul>
                            
                            <div class="inspector-section-title">Out of Scope (Non-Goals)</div>
                            <ul class="inspector-list">
            """)
            for n_goal in selected_task.get("non_goals", []):
                html_out.append(f"<li>{escape(n_goal)}</li>")
            if not selected_task.get("non_goals"):
                html_out.append("<li>None specified.</li>")
                
            html_out.append("""
                            </ul>
                            
                            <div class="inspector-section-title">Acceptance Criteria</div>
                            <ul class="inspector-list">
            """)
            for criteria in selected_task.get("acceptance", []):
                html_out.append(f"<li>{escape(criteria)}</li>")
            if not selected_task.get("acceptance"):
                html_out.append("<li>None specified.</li>")
                
            html_out.append("""
                            </ul>
                            
                            <div class="inspector-section-title">Handoff Notes / Remarks</div>
                            <p style="font-size:13px; line-height:1.6; color:#cbd5e1; margin:0 0 20px 0; background:rgba(255,255,255,0.01); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.03);">{escape(selected_task.get('notes', 'No handoff notes.'))}</p>
            """)
            
            # Comments Section
            html_out.append(f"""
                            <div class="comments-container">
                                <div class="inspector-section-title" style="border:none; margin-bottom:12px;">💬 Task Discussion & Comments</div>
                                <div style="max-height: 250px; overflow-y: auto; margin-bottom: 16px; padding-right: 4px;">
            """)
            
            task_comments = [e for e in events if str(e.get("task_id", "")) == selected_task_id and e.get("type", e.get("event")) == "note"]
            if not task_comments:
                html_out.append('<div style="font-size:12px; color:#64748b; font-style:italic; padding:10px 0;">No comments yet on this task.</div>')
            else:
                for c in task_comments:
                    html_out.append(f"""
                                    <div class="comment-item">
                                        <div class="comment-meta">
                                            <span class="comment-author">{escape(c.get('agent', 'unknown'))}</span>
                                            <span>⏱ {escape(c.get('ts', 'N/A'))}</span>
                                        </div>
                                        <div class="comment-text">{escape(c.get('text', ''))}</div>
                                    </div>
                    """)
                    
            html_out.append(f"""
                                </div>
                                <form action="/comment" method="POST" class="interactive-form" style="border-top:1px solid rgba(255,255,255,0.05); padding-top:12px;">
                                    <input type="hidden" name="task_id" value="{escape(selected_task['id'])}">
                                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                                        <label class="form-label" style="margin:0;">Speak as Agent:</label>
                                        <select name="agent" class="form-select" style="max-width:150px; padding:4px 8px; font-size:11px; height:auto; background:#1e293b;">
                                            <option value="human">human (you)</option>
                                            <option value="antigravity">antigravity</option>
                                            <option value="claude">claude</option>
                                            <option value="cursor">cursor</option>
                                            <option value="gemini">gemini</option>
                                            <option value="hermes">hermes</option>
                                        </select>
                                    </div>
                                    <textarea name="comment" class="form-textarea" placeholder="Type a comment or ask a question..." required></textarea>
                                    <button type="submit" class="form-submit-btn" style="align-self:flex-end; padding:6px 14px; font-size:12px;">Post Comment</button>
                                </form>
                            </div>
                        </div>
            """)
            
            html_out.append(f"""
                        <div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.04); border-radius:8px; padding:16px;">
                            <div class="inspector-section-title">Task Metadata</div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Owner</span>
                                <span class="inspector-meta-val" style="background:rgba(59,130,246,0.1); color:#3b82f6; padding:2px 6px; border-radius:4px;">{escape(selected_task['owner'])}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Reviewer</span>
                                <span class="inspector-meta-val" style="background:rgba(168,85,247,0.1); color:#a855f7; padding:2px 6px; border-radius:4px;">{escape(selected_task['reviewer'])}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Created By</span>
                                <span class="inspector-meta-val">{escape(selected_task.get('created_by', 'unassigned'))}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Status</span>
                                <span class="inspector-meta-val" style="text-transform:uppercase; font-size:11px;">{escape(selected_task['status'])}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Phase</span>
                                <span class="inspector-meta-val">{escape(selected_task.get('phase', '1.0'))}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Risk Level</span>
                                <span class="inspector-meta-val">{escape(selected_task['risk_level'].upper())}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Requires Human Approval</span>
                                <span class="inspector-meta-val">{escape(selected_task['requires_human_approval'])}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Depends On</span>
                                <span class="inspector-meta-val" style="font-size:11px;">{escape(', '.join(selected_task.get('depends_on', [])) or 'None')}</span>
                            </div>
                            <div class="inspector-meta-row">
                                <span class="inspector-meta-label">Related Decisions</span>
                                <span class="inspector-meta-val" style="font-size:11px;">{escape(', '.join(selected_task.get('related_decisions', [])) or 'None')}</span>
                            </div>
                            
                            <div style="margin-top:16px;">
                                <div class="inspector-section-title" style="border:none; margin-bottom:4px;">File Path</div>
                                <code style="font-size:10px; color:#64748b; background:rgba(0,0,0,0.15); padding:4px; border-radius:4px; display:block; word-break:break-all;">{escape(selected_task['file_path'])}</code>
                            </div>
            """)
                            
            # Reassign & Update Status Form
            status_opts = "".join(f'<option value="{s}" {"selected" if selected_task["status"] == s else ""}>{s}</option>' for s in ["ready", "in_progress", "review", "blocked", "done"])
            agents = ["human", "antigravity", "claude", "cursor", "gemini", "hermes", "unassigned"]
            owner_opts = "".join(f'<option value="{a}" {"selected" if selected_task["owner"] == a else ""}>{a}</option>' for a in agents)
            reviewer_opts = "".join(f'<option value="{a}" {"selected" if selected_task["reviewer"] == a else ""}>{a}</option>' for a in agents)
            
            html_out.append(f"""
                            <div style="font-size:10px; color:#475569; margin-top:16px; border-bottom: 1px solid rgba(255,255,255,0.03); padding-bottom: 12px;">
                                Created: {escape(selected_task['created_at'])}<br/>
                                Updated: {escape(selected_task['updated_at'])}
                            </div>
                            
                            <div style="margin-top:20px; background:rgba(0,0,0,0.15); border:1px solid rgba(255,255,255,0.04); padding:14px; border-radius:8px;">
                                <div class="inspector-section-title" style="border:none; margin-bottom:12px;">🔄 Reassign & Update Status</div>
                                <form action="/update_task" method="POST" class="interactive-form">
                                    <input type="hidden" name="task_id" value="{escape(selected_task['id'])}">
                                    
                                    <div class="form-row">
                                        <div>
                                            <label class="form-label">Status</label>
                                            <select name="status" class="form-select" style="background:#1e293b;">
                                                {status_opts}
                                            </select>
                                        </div>
                                        <div>
                                            <label class="form-label">Owner</label>
                                            <select name="owner" class="form-select" style="background:#1e293b;">
                                                {owner_opts}
                                            </select>
                                        </div>
                                    </div>
                                    
                                    <div style="margin-top:8px;">
                                        <label class="form-label">Reviewer</label>
                                        <select name="reviewer" class="form-select" style="background:#1e293b;">
                                            {reviewer_opts}
                                        </select>
                                    </div>
                                    
                                    <div style="margin-top:8px;">
                                        <label class="form-label">Handoff Notes / Remarks</label>
                                        <textarea name="notes" class="form-textarea" placeholder="Update handoff remarks..." style="background:#1e293b; min-height:60px;">{escape(selected_task.get('notes', ''))}</textarea>
                                    </div>
                                    
                                    <button type="submit" class="form-submit-btn" style="margin-top:8px; width:100%;">Update Task</button>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>
            """)
            
    html_out.append("""
            </div>
    """)
    # ==========================================
    # TAB PANEL: CREATE TASK
    # ==========================================
    agents = ["unassigned", "antigravity", "claude", "cursor", "gemini", "hermes", "human"]
    owner_options = "".join(f'<option value="{a}">{a}</option>' for a in agents)
    reviewer_options = "".join(f'<option value="{a}">{a}</option>' for a in agents)
    
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'create_task' else ''}">
                <div class="create-task-container">
                    <h3 style="margin-top:0; color:#f8fafc; display:flex; align-items:center; gap:8px;">🆕 Create New Active Task</h3>
                    <p style="font-size:12px; color:#94a3b8; margin-bottom:20px;">Define and register a new task. The system will automatically allocate the next sequential task ID.</p>
                    
                    <form action="/create_task" method="POST" class="interactive-form">
                        <div>
                            <label class="form-label">Task Title</label>
                            <input type="text" name="title" class="form-input" placeholder="e.g. Implement feature X or fix bug Y" required>
                        </div>
                        
                        <div class="form-row">
                            <div>
                                <label class="form-label">Assignee (Owner)</label>
                                <select name="owner" class="form-select" style="background:#0f172a;">
                                    {owner_options}
                                </select>
                            </div>
                            <div>
                                <label class="form-label">Reviewer</label>
                                <select name="reviewer" class="form-select" style="background:#0f172a;">
                                    {reviewer_options}
                                </select>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div>
                                <label class="form-label">Priority</label>
                                <select name="priority" class="form-select" style="background:#0f172a;">
                                    <option value="low">low</option>
                                    <option value="medium" selected>medium</option>
                                    <option value="high">high</option>
                                </select>
                            </div>
                            <div>
                                <label class="form-label">Risk Level</label>
                                <select name="risk_level" class="form-select" style="background:#0f172a;">
                                    <option value="low" selected>low</option>
                                    <option value="medium">medium</option>
                                    <option value="high">high</option>
                                </select>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div>
                                <label class="form-label">Phase</label>
                                <input type="text" name="phase" class="form-input" value="1.6">
                            </div>
                        </div>
                        
                        <div>
                            <label class="form-label">Objective</label>
                            <textarea name="objective" class="form-textarea" placeholder="Describe the high-level objective..." required></textarea>
                        </div>
                        
                        <div>
                            <label class="form-label">Context / Rationale</label>
                            <textarea name="context" class="form-textarea" placeholder="Why are we building this? Context..."></textarea>
                        </div>
                        
                        <div>
                            <label class="form-label">Execution Goals (One per line)</label>
                            <textarea name="goals" class="form-textarea" placeholder="e.g. Implement parser&#10;Write unit tests"></textarea>
                        </div>
                        
                        <div>
                            <label class="form-label">Acceptance Criteria (One per line)</label>
                            <textarea name="acceptance" class="form-textarea" placeholder="e.g. Validator exits 0&#10;Dashboard loads in browser" required></textarea>
                        </div>
                        
                        <button type="submit" class="form-submit-btn" style="margin-top:10px;">Create and Assign Task</button>
                    </form>
                </div>
            </div>
    """)
    
    # ==========================================
    # TAB PANEL: SYSTEM EVENTS & LOGS
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'events' else ''}">
                <h3>📜 Event Timeline (logs/agent-events.jsonl)</h3>
                
                <form class="filter-form" action="/" method="GET">
                    <input type="hidden" name="tab" value="events">
                    <input type="text" name="agent" class="filter-input" placeholder="Filter by Agent" value="{escape(filter_agent)}">
                    <input type="text" name="task" class="filter-input" placeholder="Filter by Task ID" value="{escape(filter_task)}">
                    <button type="submit" class="filter-button">Apply Filter</button>
                    {(f'<a href="/?tab=events" class="clear-link">Clear Filters</a>' if filter_agent or filter_task else '')}
                </form>
                
                <div style="font-size:12px; color:#64748b; margin-bottom:16px;">
                    Showing <b>{escape(showing_events_count)}</b> of <b>{escape(len(reversed_events))}</b> matching events.
                </div>
    """)
    
    # Draw Event Rows
    for ev in reversed_events[:30]:
        event_type = ev.get("type", ev.get("event", "note"))
        is_unknown = event_type not in ALLOWED_EVENT_TYPES
        
        # Event specific extra fields
        extra_fields = []
        for key, val in ev.items():
            if key not in ("ts", "agent", "type", "event", "detail"):
                extra_fields.append(f"<b>{escape(key)}:</b> <code>{escape(val)}</code>")
        extra_desc = " | " + " | ".join(extra_fields) if extra_fields else ""
        
        html_out.append(f"""
                <div class="event-item">
        """)
        
        if is_unknown:
            html_out.append(f"""
                    <div class="event-type-warn">
                        ⚠️ <b>Warning: unknown event type</b> <code>{escape(event_type)}</code>. This does not conform to standard ADR-0004 event vocabulary.
                    </div>
            """)
            
        html_out.append(f"""
                    <div class="event-header">
                        <span>⏱ {escape(ev.get('ts', 'N/A'))}</span>
                        <span>Agent: <b>{escape(ev.get('agent', 'unknown'))}</b></span>
                    </div>
                    <div style="font-size: 13px; color: #cbd5e1;">
                        Event: <code style="color: #3b82f6; font-weight:700;">{escape(event_type)}</code> - {escape(ev.get('detail', 'No detail provided.'))}{extra_desc}
                    </div>
                </div>
        """)
        
    html_out.append("""
            </div>
    """)
    
    # ==========================================
    # TAB PANEL: HANDOFFS & ADRS
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'handoffs' else ''}">
                <div class="split-layout">
                    <div>
                        <h3>🤝 Handoff Files</h3>
                        <div class="file-list">
    """)
    
    handoffs_list = load_handoffs(ROOT_DIR)
    for ho in handoffs_list:
        is_active = (read_file_path == f"handoffs/{ho.name}")
        html_out.append(f"""
                            <a href="/?read_file=handoffs/{escape(ho.name)}" class="file-item {'active' if is_active else ''}">
                                <span>{escape(ho.name)}</span>
                                <span style="font-size:10px; color:#64748b;">MD</span>
                            </a>
        """)
        
    html_out.append("""
                        </div>
                        
                        <h3 style="margin-top:24px;">📜 Architectural Decisions (ADRs)</h3>
                        <div class="file-list">
    """)
    
    adrs_list = load_adrs(ROOT_DIR)
    for adr in adrs_list:
        is_active = (read_file_path == f"decisions/{adr.name}")
        adr_status = detect_adr_status(adr)
        
        status_label = "unknown"
        if adr_status == "accepted":
            status_label = '<span style="color:#10b981; font-weight:700; font-size:10px;">ACCEPTED</span>'
        elif adr_status == "proposed":
            status_label = '<span style="color:#fbbf24; font-weight:700; font-size:10px;">PROPOSED</span>'
        elif adr_status == "rejected":
            status_label = '<span style="color:#ef4444; font-weight:700; font-size:10px;">REJECTED</span>'
            
        html_out.append(f"""
                            <a href="/?read_file=decisions/{escape(adr.name)}" class="file-item {'active' if is_active else ''}">
                                <span>{escape(adr.name)}</span>
                                <span>{status_label}</span>
                            </a>
        """)
        
    html_out.append("""
                        </div>
                    </div>
                    
                    <div>
                        <h3>📑 Markdown File Reader</h3>
    """)
    
    if read_file_path:
        resolved_read_path = ROOT_DIR / read_file_path
        # Safety check: prevent path traversal attacks by resolving and checking parent path
        if resolved_read_path.exists() and ROOT_DIR in resolved_read_path.resolve().parents:
            try:
                markdown_text = resolved_read_path.read_text(encoding="utf-8")
                html_out.append(f"""
                        <div style="font-size:11px; color:#64748b; margin-bottom:8px;">Path: <code>{escape(read_file_path)}</code></div>
                        <pre class="reader-panel" style="white-space: pre-wrap; font-family: monospace; font-size:12px; background:rgba(0,0,0,0.2);">{escape(markdown_text)}</pre>
                """)
            except Exception as e:
                html_out.append(f'<div class="event-type-warn">Failed to read file: {escape(str(e))}</div>')
        else:
            html_out.append('<div class="event-type-warn">Access Denied / Invalid File Path</div>')
    else:
        html_out.append("""
                        <div style="color:#475569; padding:60px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                            Select a handoff or ADR file from the left to read its contents.
                        </div>
        """)
        
    html_out.append("""
                    </div>
                </div>
            </div>
    """)
    
    # ==========================================
    # TAB PANEL: AGENTS / TOOLS
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'agents_tools' else ''}">
                <h3>🤖 Agents / Tools Inventory</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    Read-only view of <code>runtime/registry/cli_inventory.yaml</code> and
                    <code>runtime/status/daemon_status.json</code>. Run
                    <code>python -m daemon.daemon --once</code> to refresh.
                </p>
    """)

    inventory_summary = (cli_inventory or {}).get("summary", {})
    daemon_summary = (daemon_status or {}).get("summary", inventory_summary)
    daemon_run_state = "missing"
    if daemon_status_errors:
        daemon_run_state = "error"
    elif daemon_status:
        daemon_run_state = daemon_status.get("status", "ok")

    html_out.append(f"""
                <div class="daemon-health-grid">
                    <div class="daemon-health-card">
                        <div class="daemon-health-label">Tools Tracked</div>
                        <div class="daemon-health-value">{escape(daemon_summary.get('total', inventory_summary.get('total', 'N/A')))}</div>
                    </div>
                    <div class="daemon-health-card">
                        <div class="daemon-health-label">Available</div>
                        <div class="daemon-health-value" style="color:#34d399;">{escape(daemon_summary.get('available', inventory_summary.get('available', 'N/A')))}</div>
                    </div>
                    <div class="daemon-health-card">
                        <div class="daemon-health-label">Missing</div>
                        <div class="daemon-health-value" style="color:#f87171;">{escape(daemon_summary.get('missing', inventory_summary.get('missing', 'N/A')))}</div>
                    </div>
                    <div class="daemon-health-card">
                        <div class="daemon-health-label">Last Daemon Run</div>
                        <div class="daemon-health-value" style="font-size:13px;">{escape((daemon_status or {}).get('last_run_at', 'N/A'))}</div>
                    </div>
                    <div class="daemon-health-card">
                        <div class="daemon-health-label">Daemon Status</div>
                        <div class="daemon-health-value" style="font-size:13px; text-transform:uppercase;">{escape(daemon_run_state)}</div>
                    </div>
                </div>
    """)

    if cli_inventory_errors or daemon_status_errors:
        for err in cli_inventory_errors + daemon_status_errors:
            html_out.append(f'<div class="event-type-warn">{escape(err)}</div>')

    if daemon_status and daemon_status.get("errors"):
        for err in daemon_status.get("errors", []):
            html_out.append(f'<div class="event-type-warn">Daemon error: {escape(err)}</div>')

    if cli_inventory and cli_inventory.get("tools"):
        html_out.append("""
                <table class="tools-table">
                    <thead>
                        <tr>
                            <th>Tool</th>
                            <th>Status</th>
                            <th>Version</th>
                            <th>Path</th>
                            <th>Last Checked</th>
                            <th>Notes</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        for tool in cli_inventory.get("tools", []):
            if not isinstance(tool, dict):
                continue
            available = tool.get("available", False)
            status_class = "tool-available" if available else "tool-missing"
            status_label = "available" if available else "missing"
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(tool.get('display_name', tool.get('id', 'unknown')))}</b><br/><code style="font-size:10px; color:#64748b;">{escape(tool.get('id', ''))}</code></td>
                            <td class="{status_class}">{escape(status_label)}</td>
                            <td>{escape(tool.get('version') or '—')}</td>
                            <td><code style="font-size:10px; word-break:break-all;">{escape(tool.get('path') or '—')}</code></td>
                            <td style="font-size:11px; color:#94a3b8;">{escape(tool.get('last_checked', 'N/A'))}</td>
                            <td style="font-size:11px; color:#94a3b8;">{escape(tool.get('notes') or '—')}</td>
                        </tr>
            """)
        html_out.append("""
                    </tbody>
                </table>
        """)
    else:
        html_out.append("""
                <div style="color:#475569; padding:40px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                    No CLI inventory found yet. Run <code>python -m daemon.daemon --once</code> to populate runtime/registry/cli_inventory.yaml.
                </div>
        """)

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: SKILLS
    # ==========================================
    all_skills = []
    if skills_registry and isinstance(skills_registry.get("skills"), list):
        all_skills = [s for s in skills_registry["skills"] if isinstance(s, dict)]

    filtered_skills = all_skills
    if skill_filter_agent:
        filtered_skills = [
            s for s in filtered_skills
            if skill_filter_agent.lower() in [str(a).lower() for a in s.get("allowed_agents", [])]
        ]
    if skill_filter_risk:
        filtered_skills = [s for s in filtered_skills if str(s.get("risk_level", "")).lower() == skill_filter_risk.lower()]
    if skill_filter_approval:
        filtered_skills = [s for s in filtered_skills if str(s.get("approval_level", "")).lower() == skill_filter_approval.lower()]
    if skill_filter_category:
        filtered_skills = [s for s in filtered_skills if str(s.get("category", "")).lower() == skill_filter_category.lower()]

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'skills' else ''}">
                <h3>🧩 Skills Registry</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    Read-only view of <code>skills/registry.yaml</code>. Phase 2.1 does not execute skills.
                </p>
                <form class="filter-form" action="/" method="GET">
                    <input type="hidden" name="tab" value="skills">
                    <input type="text" name="skill_agent" class="filter-input" placeholder="Filter by agent" value="{escape(skill_filter_agent)}">
                    <input type="text" name="skill_risk" class="filter-input" placeholder="Risk (low/medium/high)" value="{escape(skill_filter_risk)}">
                    <input type="text" name="skill_approval" class="filter-input" placeholder="Approval" value="{escape(skill_filter_approval)}">
                    <input type="text" name="skill_category" class="filter-input" placeholder="Category" value="{escape(skill_filter_category)}">
                    <button type="submit" class="filter-button">Apply</button>
                    {(f'<a href="/?tab=skills" class="clear-link">Clear</a>' if skill_filter_agent or skill_filter_risk or skill_filter_approval or skill_filter_category else '')}
                </form>
                <div style="font-size:12px; color:#64748b; margin-bottom:16px;">
                    Showing <b>{escape(len(filtered_skills))}</b> of <b>{escape(len(all_skills))}</b> skills.
                </div>
    """)

    if skills_registry_errors:
        for err in skills_registry_errors:
            html_out.append(f'<div class="event-type-warn">{escape(err)}</div>')
    elif filtered_skills:
        html_out.append("""
                <table class="tools-table">
                    <thead>
                        <tr>
                            <th>Skill</th>
                            <th>Category</th>
                            <th>Agents</th>
                            <th>CLIs</th>
                            <th>MCPs</th>
                            <th>Risk</th>
                            <th>Approval</th>
                            <th>Status</th>
                            <th>Notes</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        for skill in filtered_skills:
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(skill.get('name', ''))}</b><br/><code style="font-size:10px; color:#64748b;">{escape(skill.get('id', ''))}</code></td>
                            <td>{escape(skill.get('category', '—'))}</td>
                            <td style="font-size:11px;">{escape(', '.join(skill.get('allowed_agents', [])) or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(skill.get('required_clis', [])) or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(skill.get('required_mcps', [])) or '—')}</td>
                            <td>{escape(skill.get('risk_level', '—'))}</td>
                            <td>{escape(skill.get('approval_level', '—'))}</td>
                            <td>{escape(skill.get('status', '—'))}</td>
                            <td style="font-size:11px; color:#94a3b8;">{escape(skill.get('notes', '—'))}</td>
                        </tr>
            """)
        html_out.append("""
                    </tbody>
                </table>
        """)
    else:
        html_out.append("""
                <div style="color:#475569; padding:40px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                    No skills match the current filters.
                </div>
        """)

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: MCPS
    # ==========================================
    all_mcps = []
    if mcps_registry and isinstance(mcps_registry.get("mcps"), list):
        all_mcps = [m for m in mcps_registry["mcps"] if isinstance(m, dict)]

    filtered_mcps = all_mcps
    if mcp_filter_agent:
        filtered_mcps = [
            m for m in filtered_mcps
            if mcp_filter_agent.lower() in [str(a).lower() for a in m.get("allowed_agents", [])]
        ]
    if mcp_filter_status:
        filtered_mcps = [m for m in filtered_mcps if str(m.get("status", "")).lower() == mcp_filter_status.lower()]

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'mcps' else ''}">
                <h3>🔌 MCP Registry</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    Read-only view of <code>mcps/registry.yaml</code>. Phase 2.1 does not execute MCP servers.
                </p>
                <form class="filter-form" action="/" method="GET">
                    <input type="hidden" name="tab" value="mcps">
                    <input type="text" name="mcp_agent" class="filter-input" placeholder="Filter by agent" value="{escape(mcp_filter_agent)}">
                    <input type="text" name="mcp_status" class="filter-input" placeholder="Status (planned/...)" value="{escape(mcp_filter_status)}">
                    <button type="submit" class="filter-button">Apply</button>
                    {(f'<a href="/?tab=mcps" class="clear-link">Clear</a>' if mcp_filter_agent or mcp_filter_status else '')}
                </form>
                <div style="font-size:12px; color:#64748b; margin-bottom:16px;">
                    Showing <b>{escape(len(filtered_mcps))}</b> of <b>{escape(len(all_mcps))}</b> MCPs.
                </div>
    """)

    if mcps_registry_errors:
        for err in mcps_registry_errors:
            html_out.append(f'<div class="event-type-warn">{escape(err)}</div>')
    elif filtered_mcps:
        html_out.append("""
                <table class="tools-table">
                    <thead>
                        <tr>
                            <th>MCP</th>
                            <th>Status</th>
                            <th>Transport</th>
                            <th>Agents</th>
                            <th>Capabilities</th>
                            <th>Secret?</th>
                            <th>Risk</th>
                            <th>Approval</th>
                            <th>Notes</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        for mcp in filtered_mcps:
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(mcp.get('name', ''))}</b><br/><code style="font-size:10px; color:#64748b;">{escape(mcp.get('id', ''))}</code></td>
                            <td>{escape(mcp.get('status', '—'))}</td>
                            <td>{escape(mcp.get('transport', '—'))}</td>
                            <td style="font-size:11px;">{escape(', '.join(mcp.get('allowed_agents', [])) or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(mcp.get('capabilities', [])) or '—')}</td>
                            <td>{escape(mcp.get('requires_secret', '—'))}</td>
                            <td>{escape(mcp.get('risk_level', '—'))}</td>
                            <td>{escape(mcp.get('approval_level', '—'))}</td>
                            <td style="font-size:11px; color:#94a3b8;">{escape(mcp.get('notes', '—'))}</td>
                        </tr>
            """)
        html_out.append("""
                    </tbody>
                </table>
        """)
    else:
        html_out.append("""
                <div style="color:#475569; padding:40px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                    No MCPs match the current filters.
                </div>
        """)

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: TEAMS
    # ==========================================
    all_teams = []
    if teams_registry and isinstance(teams_registry.get("teams"), list):
        all_teams = [t for t in teams_registry["teams"] if isinstance(t, dict)]

    filtered_teams = all_teams
    if team_filter_status:
        filtered_teams = [t for t in filtered_teams if str(t.get("status", "")).lower() == team_filter_status.lower()]
    if team_filter_agent:
        agent_lower = team_filter_agent.lower()
        filtered_teams = [
            t for t in filtered_teams
            if any(
                agent_lower == str(m.get("agent", "")).lower()
                for m in t.get("members", [])
                if isinstance(m, dict)
            )
            or (
                isinstance(t.get("orchestrator"), dict)
                and agent_lower == str(t["orchestrator"].get("agent", "")).lower()
            )
        ]
    if team_filter_skill:
        skill_lower = team_filter_skill.lower()
        filtered_teams = [
            t for t in filtered_teams
            if skill_lower in [str(s).lower() for s in t.get("required_skills", [])]
            or skill_lower in [str(s).lower() for s in t.get("optional_skills", [])]
        ]

    active_task_options = []
    active_tasks_dir = ROOT_DIR / "tasks" / "active"
    if active_tasks_dir.exists():
        for task_file in sorted(active_tasks_dir.glob("*.yaml")):
            if task_file.name == "EXAMPLE.yaml":
                continue
            active_task_options.append(task_file.stem)

    team_suggestions = []
    if suggest_task_id:
        safe_task_id = Path(suggest_task_id).name
        task_path = None
        tasks_root = (ROOT_DIR / "tasks").resolve()
        for folder in ("active", "done", "blocked"):
            candidate = (ROOT_DIR / "tasks" / folder / f"{safe_task_id}.yaml").resolve()
            try:
                candidate.relative_to(tasks_root)
            except ValueError:
                continue
            if candidate.exists():
                task_path = candidate
                break
        if task_path and task_path.exists():
            scripts_dir = str(ROOT_DIR / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            try:
                from suggest_team import suggest_teams
                team_suggestions = suggest_teams(ROOT_DIR, task_path=task_path, limit=5)
            except Exception:
                team_suggestions = []

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'teams' else ''}">
                <h3>👥 Teams Registry</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    Read-only view of <code>teams/registry.yaml</code>. Phase 2.2 does not assign tasks automatically.
                </p>
                <form class="filter-form" action="/" method="GET">
                    <input type="hidden" name="tab" value="teams">
                    <input type="text" name="team_status" class="filter-input" placeholder="Status" value="{escape(team_filter_status)}">
                    <input type="text" name="team_agent" class="filter-input" placeholder="Agent" value="{escape(team_filter_agent)}">
                    <input type="text" name="team_skill" class="filter-input" placeholder="Skill" value="{escape(team_filter_skill)}">
                    <button type="submit" class="filter-button">Apply</button>
                </form>
                <div style="font-size:12px; color:#64748b; margin-bottom:16px;">
                    Showing <b>{escape(len(filtered_teams))}</b> of <b>{escape(len(all_teams))}</b> teams.
                </div>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px; margin-bottom:20px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">Team Suggestion (read-only)</div>
                    <form class="filter-form" action="/" method="GET" style="margin-bottom:0;">
                        <input type="hidden" name="tab" value="teams">
                        <select name="suggest_task" class="filter-input" style="min-width:220px;">
                            <option value="">Select task...</option>
                            {''.join(f'<option value="{escape(tid)}" {"selected" if tid == suggest_task_id else ""}>{escape(tid)}</option>' for tid in active_task_options)}
                        </select>
                        <button type="submit" class="filter-button">Suggest Team</button>
                    </form>
    """)

    if suggest_task_id and team_suggestions:
        html_out.append("""
                    <table class="tools-table" style="margin-top:12px;">
                        <thead><tr><th>Team</th><th>Score</th><th>Reviewer</th><th>Matching Skills</th><th>Notes</th></tr></thead>
                        <tbody>
        """)
        for sug in team_suggestions:
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(sug.get('team_name', ''))}</b><br/><code style="font-size:10px;">{escape(sug.get('team_id', ''))}</code></td>
                            <td>{escape(sug.get('score', ''))}</td>
                            <td>{escape(sug.get('recommended_reviewer') or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(sug.get('matching_skills', [])) or '—')}</td>
                            <td style="font-size:11px; color:#94a3b8;">{escape(sug.get('notes', ''))}</td>
                        </tr>
            """)
        html_out.append("</tbody></table>")
    elif suggest_task_id:
        html_out.append('<div style="font-size:12px; color:#64748b; margin-top:10px;">No suggestions for selected task.</div>')

    html_out.append("</div>")

    if teams_registry_errors:
        for err in teams_registry_errors:
            html_out.append(f'<div class="event-type-warn">{escape(err)}</div>')
    elif filtered_teams:
        html_out.append("""
                <table class="tools-table">
                    <thead>
                        <tr>
                            <th>Team</th>
                            <th>Status</th>
                            <th>Orchestrator</th>
                            <th>Reviewer</th>
                            <th>Members</th>
                            <th>Required Skills</th>
                            <th>MCPs</th>
                            <th>Approval</th>
                            <th>Notes</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        for team in filtered_teams:
            orch = team.get("orchestrator", {})
            rev = team.get("default_reviewer", {})
            orch_agent = orch.get("agent", "—") if isinstance(orch, dict) else "—"
            rev_agent = rev.get("agent", "—") if isinstance(rev, dict) else "—"
            members_txt = ", ".join(
                f"{m.get('agent')}({m.get('role')})"
                for m in team.get("members", [])
                if isinstance(m, dict)
            )
            policy = team.get("approval_policy", {})
            approval_txt = policy.get("default_level", "—") if isinstance(policy, dict) else "—"
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(team.get('name', ''))}</b><br/><code style="font-size:10px; color:#64748b;">{escape(team.get('id', ''))}</code></td>
                            <td>{escape(team.get('status', '—'))}</td>
                            <td>{escape(orch_agent)}</td>
                            <td>{escape(rev_agent)}</td>
                            <td style="font-size:11px;">{escape(members_txt or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(team.get('required_skills', [])) or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(team.get('allowed_mcps', [])) or '—')}</td>
                            <td>{escape(approval_txt)}</td>
                            <td style="font-size:11px; color:#94a3b8;">{escape(team.get('notes', '—'))}</td>
                        </tr>
            """)
        html_out.append("</tbody></table>")
    else:
        html_out.append("""
                <div style="color:#475569; padding:40px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                    No teams match the current filters.
                </div>
        """)

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: ROLES
    # ==========================================
    all_roles = []
    if roles_registry and isinstance(roles_registry.get("roles"), list):
        all_roles = [r for r in roles_registry["roles"] if isinstance(r, dict)]

    filtered_roles = all_roles
    if role_filter_agent:
        agent_lower = role_filter_agent.lower()
        filtered_roles = [
            r for r in filtered_roles
            if any(agent_lower == str(a).lower() for a in r.get("allowed_agents", []))
        ]
    if role_filter_risk:
        filtered_roles = [r for r in filtered_roles if str(r.get("risk_level", "")).lower() == role_filter_risk.lower()]
    if role_filter_approval:
        filtered_roles = [r for r in filtered_roles if str(r.get("approval_level", "")).lower() == role_filter_approval.lower()]
    if role_filter_can_execute:
        want = role_filter_can_execute.lower() == "true"
        filtered_roles = [r for r in filtered_roles if bool(r.get("can_execute")) == want]
    if role_filter_can_review:
        want = role_filter_can_review.lower() == "true"
        filtered_roles = [r for r in filtered_roles if bool(r.get("can_review")) == want]

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'roles' else ''}">
                <h3>🎭 Roles Registry</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    Read-only view of <code>roles/registry.yaml</code>.
                </p>
                <form class="filter-form" action="/" method="GET">
                    <input type="hidden" name="tab" value="roles">
                    <input type="text" name="role_agent" class="filter-input" placeholder="Agent" value="{escape(role_filter_agent)}">
                    <input type="text" name="role_risk" class="filter-input" placeholder="Risk" value="{escape(role_filter_risk)}">
                    <input type="text" name="role_approval" class="filter-input" placeholder="Approval" value="{escape(role_filter_approval)}">
                    <input type="text" name="role_can_execute" class="filter-input" placeholder="can_execute true/false" value="{escape(role_filter_can_execute)}">
                    <input type="text" name="role_can_review" class="filter-input" placeholder="can_review true/false" value="{escape(role_filter_can_review)}">
                    <button type="submit" class="filter-button">Apply</button>
                </form>
                <div style="font-size:12px; color:#64748b; margin-bottom:16px;">
                    Showing <b>{escape(len(filtered_roles))}</b> of <b>{escape(len(all_roles))}</b> roles.
                </div>
    """)

    if roles_registry_errors:
        for err in roles_registry_errors:
            html_out.append(f'<div class="event-type-warn">{escape(err)}</div>')
    elif filtered_roles:
        html_out.append("""
                <table class="tools-table">
                    <thead>
                        <tr>
                            <th>Role</th>
                            <th>Agents</th>
                            <th>Required Skills</th>
                            <th>MCPs</th>
                            <th>Risk</th>
                            <th>Approval</th>
                            <th>Delegate</th>
                            <th>Review</th>
                            <th>Execute</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        for role in filtered_roles:
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(role.get('name', ''))}</b><br/><code style="font-size:10px; color:#64748b;">{escape(role.get('id', ''))}</code></td>
                            <td style="font-size:11px;">{escape(', '.join(role.get('allowed_agents', [])) or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(role.get('required_skills', [])) or '—')}</td>
                            <td style="font-size:11px;">{escape(', '.join(role.get('allowed_mcps', [])) or '—')}</td>
                            <td>{escape(role.get('risk_level', '—'))}</td>
                            <td>{escape(role.get('approval_level', '—'))}</td>
                            <td>{escape(role.get('can_delegate', '—'))}</td>
                            <td>{escape(role.get('can_review', '—'))}</td>
                            <td>{escape(role.get('can_execute', '—'))}</td>
                        </tr>
            """)
        html_out.append("</tbody></table>")
    else:
        html_out.append("""
                <div style="color:#475569; padding:40px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                    No roles match the current filters.
                </div>
        """)

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: OBSIDIAN SYNC
    # ==========================================
    obs_vault = obsidian_mapping.get("vault_path") if obsidian_mapping else None
    obs_enabled = obsidian_mapping.get("sync_enabled") if obsidian_mapping else None
    obs_dry_default = obsidian_mapping.get("dry_run_default") if obsidian_mapping else None
    obs_root_folder = obsidian_mapping.get("vault_root_folder", "AgenticOS") if obsidian_mapping else "AgenticOS"

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'obsidian' else ''}">
                <h3>📓 Obsidian Vault Sync</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    <strong>One-way only:</strong> repo → vault export. No vault → repo import.
                    Dashboard does not trigger sync. Use <code>python scripts/sync_obsidian.py</code> manually.
                </p>
    """)

    if obsidian_mapping_errors:
        for err in obsidian_mapping_errors:
            html_out.append(f'<div class="event-type-warn">{escape(err)}</div>')
    elif obsidian_mapping:
        last_synced = obsidian_last_sync.get("synced_at", "—") if obsidian_last_sync else "—"
        last_written = obsidian_last_sync.get("notes_written", "—") if obsidian_last_sync else "—"
        html_out.append(f"""
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px; margin-bottom:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">Configuration</div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Vault path</span><span class="inspector-meta-val">{escape(str(obs_vault) if obs_vault else '(not configured)')}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">sync_enabled</span><span class="inspector-meta-val">{escape(str(obs_enabled))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">dry_run_default</span><span class="inspector-meta-val">{escape(str(obs_dry_default))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Vault folder</span><span class="inspector-meta-val">{escape(str(obs_root_folder))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Notes planned (dry-run)</span><span class="inspector-meta-val">{escape(str(obsidian_notes_planned) if obsidian_notes_planned is not None else '—')}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Last sync</span><span class="inspector-meta-val">{escape(str(last_synced))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Last notes written</span><span class="inspector-meta-val">{escape(str(last_written))}</span></div>
                </div>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">CLI Commands</div>
                    <pre style="font-size:12px; color:#cbd5e1; white-space:pre-wrap;">python scripts/sync_obsidian.py --dry-run
python scripts/sync_obsidian.py --vault "&lt;path-to-vault&gt;"</pre>
                </div>
        """)
        if obsidian_sync_errors:
            for err in obsidian_sync_errors:
                html_out.append(f'<div class="event-type-warn" style="margin-top:12px;">{escape(err)}</div>')

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: ORCHESTRATOR
    # ==========================================
    orch_task_options = []
    orch_tasks_dir = ROOT_DIR / "tasks" / "active"
    if orch_tasks_dir.exists():
        for task_file in sorted(orch_tasks_dir.glob("*.yaml")):
            if task_file.name == "EXAMPLE.yaml":
                continue
            orch_task_options.append(task_file.stem)

    orch_run_id = orchestrator_state.get("run_id", "—") if orchestrator_state else "—"
    orch_task_id = orchestrator_state.get("task_id", "—") if orchestrator_state else "—"
    orch_team = orchestrator_state.get("selected_team", "—") if orchestrator_state else "—"
    orch_agents = ", ".join(orchestrator_state.get("selected_agents", [])) if orchestrator_state else "—"
    orch_approval = orchestrator_state.get("approval_required", "—") if orchestrator_state else "—"
    orch_reason = orchestrator_state.get("approval_reason", "—") if orchestrator_state else "—"
    orch_next = orchestrator_state.get("next_action", "—") if orchestrator_state else "—"
    orch_plan_path = orchestrator_state.get("plan_path", "—") if orchestrator_state else "—"
    orch_ctx_path = orchestrator_state.get("context_pack_path", "—") if orchestrator_state else "—"
    orch_warnings = orchestrator_state.get("warnings", []) if orchestrator_state else []
    orch_errors = orchestrator_state.get("errors", []) if orchestrator_state else []

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'orchestrator' else ''}">
                <h3>🧭 Orchestrator</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    Read-only view of latest LangGraph orchestration plan. Does not execute agents or run LangGraph.
                </p>
    """)
    if orch_errors:
        html_out.append(
            '<div class="health-card health-err" style="background:rgba(239,68,68,0.12); border-left:4px solid #ef4444; '
            'border-radius:6px; padding:12px; margin-bottom:16px;">'
            '<h4 style="margin:0 0 8px 0; color:#f87171;">Orchestrator errors — fix task input</h4>'
            + "".join(f'<div style="font-size:11px; color:#fca5a5;">{escape(str(e))}</div>' for e in orch_errors)
            + "</div>"
        )
    html_out.append(f"""
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px; margin-bottom:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">Latest Run</div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Run ID</span><span class="inspector-meta-val">{escape(str(orch_run_id))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Task ID</span><span class="inspector-meta-val">{escape(str(orch_task_id))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Selected team</span><span class="inspector-meta-val">{escape(str(orch_team))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Agents</span><span class="inspector-meta-val">{escape(str(orch_agents))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Approval required</span><span class="inspector-meta-val">{escape(str(orch_approval))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Approval reason</span><span class="inspector-meta-val" style="font-size:11px;">{escape(str(orch_reason))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Next action</span><span class="inspector-meta-val">{escape(str(orch_next))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Plan path</span><span class="inspector-meta-val" style="font-size:10px;">{escape(str(orch_plan_path))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Context pack</span><span class="inspector-meta-val" style="font-size:10px;">{escape(str(orch_ctx_path))}</span></div>
                </div>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">CLI Hint</div>
                    <pre style="font-size:12px; color:#cbd5e1; white-space:pre-wrap;">python scripts/orchestrate_task.py --task tasks/active/T-EXAMPLE.yaml
python scripts/orchestrate_task.py --task tasks/active/&lt;task-id&gt;.yaml --json</pre>
                    <div style="font-size:11px; color:#64748b; margin-top:8px;">Active tasks: {escape(', '.join(orch_task_options[:8]) or '—')}</div>
                </div>
    """)

    if orchestrator_errors:
        for err in orchestrator_errors:
            html_out.append(f'<div class="event-type-warn" style="margin-top:12px;">{escape(err)}</div>')
    if orch_warnings:
        html_out.append('<div style="margin-top:12px; font-size:11px; color:#fbbf24;">Warnings: ' + escape("; ".join(orch_warnings[:5])) + '</div>')
    if orch_errors:
        html_out.append('<div style="margin-top:8px; font-size:11px; color:#f87171;">Errors: ' + escape("; ".join(orch_errors)) + '</div>')
    if not orchestrator_state:
        html_out.append('<div style="margin-top:12px; font-size:12px; color:#64748b;">No orchestration run yet. Run the CLI to generate latest_state.json.</div>')

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: DISPATCH (Phase 3.0 preview + Phase 3.2 read-only execution status)
    # ==========================================
    dp_run_id = dispatch_preview.get("run_id", "—") if dispatch_preview else "—"
    dp_task = dispatch_preview.get("task_id", "—") if dispatch_preview else "—"
    dp_adapter = dispatch_preview.get("adapter_id", "—") if dispatch_preview else "—"
    dp_allowed = dispatch_preview.get("dispatch_allowed", "—") if dispatch_preview else "—"
    dp_command = dispatch_preview.get("command", "—") if dispatch_preview else "—"
    dp_workdir = dispatch_preview.get("working_directory", "—") if dispatch_preview else "—"
    dp_risk = dispatch_preview.get("risk_gate", {}).get("approval_level", "—") if dispatch_preview else "—"
    dp_approval = dispatch_preview.get("approval_gate", {}).get("approval_status", "—") if dispatch_preview else "—"
    dp_errors = dispatch_preview.get("errors", []) if dispatch_preview else []
    de_executed = dispatch_exec_result.get("executed", "—") if dispatch_exec_result else "—"
    de_allowed = dispatch_exec_result.get("execution_allowed", "—") if dispatch_exec_result else "—"
    de_exit = dispatch_exec_result.get("exit_code", "—") if dispatch_exec_result else "—"
    de_blocked = dispatch_exec_result.get("blocked_reasons", []) if dispatch_exec_result else []
    de_approval_status = dispatch_exec_result.get("approval_status", "—") if dispatch_exec_result else "—"

    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'dispatch' else ''}">
                <h3>🚀 Dispatch Status</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    <strong>Read-only.</strong> Preview and execution status only. Operator must use CLI;
                    this dashboard does not run agents, MCPs, or subprocesses.
                </p>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px; margin-bottom:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">Latest Preview</div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Run ID</span><span class="inspector-meta-val">{escape(str(dp_run_id))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Task</span><span class="inspector-meta-val">{escape(str(dp_task))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Adapter</span><span class="inspector-meta-val">{escape(str(dp_adapter))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Dispatch allowed</span><span class="inspector-meta-val">{escape(str(dp_allowed))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Risk gate</span><span class="inspector-meta-val">{escape(str(dp_risk))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Approval status</span><span class="inspector-meta-val">{escape(str(dp_approval))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Command</span><span class="inspector-meta-val" style="font-size:10px;">{escape(str(dp_command))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Working dir</span><span class="inspector-meta-val" style="font-size:10px;">{escape(str(dp_workdir))}</span></div>
                </div>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px; margin-bottom:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">Latest Execution Result</div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Executed</span><span class="inspector-meta-val">{escape(str(de_executed))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Execution allowed</span><span class="inspector-meta-val">{escape(str(de_allowed))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Exit code</span><span class="inspector-meta-val">{escape(str(de_exit))}</span></div>
                    <div class="inspector-meta-row"><span class="inspector-meta-label">Approval status</span><span class="inspector-meta-val">{escape(str(de_approval_status))}</span></div>
                </div>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:16px;">
                    <div class="inspector-section-title" style="border:none; margin-bottom:10px;">Operator CLI (command line only)</div>
                    <pre style="font-size:12px; color:#cbd5e1; white-space:pre-wrap;">python scripts/preview_dispatch.py --adapter local-python-exec-test --json
python scripts/approve_dispatch.py --preview runtime/dispatch/previews/&lt;run_id&gt;/preview.json --level reviewer --approved-by operator
python scripts/execute_dispatch.py --preview runtime/dispatch/previews/&lt;run_id&gt;/preview.json --dry-run
python scripts/execute_dispatch.py --preview ... --execute --approval runtime/dispatch/approvals/&lt;id&gt;.json</pre>
                </div>
    """)
    if dispatch_preview_errors:
        for err in dispatch_preview_errors:
            html_out.append(f'<div class="event-type-warn" style="margin-top:12px;">{escape(err)}</div>')
    for err in dispatch_exec_request_errors + dispatch_exec_result_errors:
        html_out.append(f'<div class="event-type-warn" style="margin-top:12px;">{escape(err)}</div>')
    if dp_errors:
        html_out.append('<div style="margin-top:8px; font-size:11px; color:#f87171;">Preview errors: ' + escape("; ".join(str(e) for e in dp_errors[:5])) + '</div>')
    if de_blocked:
        html_out.append('<div style="margin-top:8px; font-size:11px; color:#f87171;">Blocked: ' + escape("; ".join(str(e) for e in de_blocked[:5])) + '</div>')
    if not dispatch_preview:
        html_out.append('<div style="margin-top:12px; font-size:12px; color:#64748b;">No dispatch preview yet. Run orchestration then <code>python scripts/preview_dispatch.py</code>.</div>')
    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: EXECUTION RUNS (Phase 3.7C local builder)
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'execution_runs' else ''}">
                <h3>Execution Runs</h3>
                <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
                    <strong>Read-only.</strong> Recent local-builder run artifacts from
                    <code>runtime/dispatch/runs/</code> plus claim/lifecycle state from
                    <code>runtime/dispatch/local_builder_claims/</code> and task YAML.
                    This page does not execute, retry, approve, merge, push, or deploy anything.
                </p>
                <form method="GET" class="filter-bar" style="margin-bottom:16px;">
                    <input type="hidden" name="tab" value="execution_runs">
                    <input type="text" name="run_adapter" class="filter-input" placeholder="Filter by adapter" value="{escape(run_filter_adapter)}">
                    <input type="text" name="run_status" class="filter-input" placeholder="Filter by run status" value="{escape(run_filter_status)}">
                    <button type="submit" class="filter-btn">Apply</button>
                    {(f'<a href="/?tab=execution_runs" class="clear-link">Clear</a>' if run_filter_adapter or run_filter_status else '')}
                </form>
    """)

    if execution_run_errors:
        html_out.append(
            '<div class="event-type-warn">Run artifact warnings: '
            + escape("; ".join(execution_run_errors[:5]))
            + (" ..." if len(execution_run_errors) > 5 else "")
            + "</div>"
        )

    if execution_runs:
        html_out.append("""
                <table class="tools-table">
                    <thead>
                        <tr>
                            <th>Run</th>
                            <th>Task / Adapter</th>
                            <th>Route</th>
                            <th>Status</th>
                            <th>Claim / Lifecycle</th>
                            <th>Timestamps</th>
                            <th>Worktree</th>
                            <th>Verification</th>
                            <th>Blocked Reasons</th>
                            <th>Handoff</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        for run in execution_runs:
            blocked = run.get("blocked_reasons") or []
            blocked_text = "; ".join(str(reason) for reason in blocked) if blocked else "-"
            status = str(run.get("status") or "unknown")
            status_color = "#94a3b8"
            if status == "completed_verified":
                status_color = "#34d399"
            elif status in {"completed_unverified", "blocked", "failed", "timed_out", "scope_violation"}:
                status_color = "#f87171"
            verification_status = str(run.get("verification_status") or "not_recorded")
            verification_color = "#94a3b8"
            if verification_status == "passed":
                verification_color = "#34d399"
            elif verification_status in {"failed", "timed_out", "parse_error"}:
                verification_color = "#f87171"
            claim_state = str(run.get("claim_state") or "unknown")
            claim_color = "#94a3b8"
            if claim_state == "claimed":
                claim_color = "#fbbf24"
            elif claim_state == "review_pending":
                claim_color = "#60a5fa"
            elif claim_state == "running":
                claim_color = "#22d3ee"
            elif claim_state == "claimed_other_run":
                claim_color = "#fb923c"
            task_lifecycle_status = str(run.get("task_lifecycle_status") or "-")
            active_claim_run_id = str(run.get("active_claim_run_id") or "")
            run_warnings = run.get("errors") or []
            warning_html = ""
            if run_warnings:
                warning_html = (
                    '<br/><span style="font-size:10px; color:#fbbf24;">'
                    + escape("; ".join(str(err) for err in run_warnings[:2]))
                    + "</span>"
                )
            html_out.append(f"""
                        <tr>
                            <td><b>{escape(run.get('run_id') or '-')}</b><br/><code style="font-size:10px; color:#64748b;">{escape(run.get('run_dir') or '')}</code>{warning_html}</td>
                            <td>{escape(run.get('task_id') or '-')}<br/><code style="font-size:10px; color:#94a3b8;">{escape(run.get('adapter_id') or '-')}</code></td>
                            <td><code style="font-size:10px;">{escape(run.get('route') or '-')}</code></td>
                            <td><span style="color:{status_color}; font-weight:700;">{escape(status)}</span></td>
                            <td><span style="color:{claim_color}; font-weight:700;">{escape(claim_state)}</span><br/><span style="font-size:10px; color:#94a3b8;">task: {escape(task_lifecycle_status)}</span>{('<br/><span style="font-size:10px; color:#64748b;">active claim: ' + escape(active_claim_run_id) + '</span>') if active_claim_run_id else ''}</td>
                            <td style="font-size:11px; color:#cbd5e1;">Start: {escape(run.get('started_at') or '-')}<br/>Finish: {escape(run.get('finished_at') or '-')}</td>
                            <td><code style="font-size:10px; word-break:break-all;">{escape(run.get('worktree_path') or '-')}</code></td>
                            <td><span style="color:{verification_color}; font-weight:700;">{escape(verification_status)}</span></td>
                            <td style="font-size:11px; color:#fca5a5;">{escape(blocked_text)}</td>
                            <td><code style="font-size:10px; word-break:break-all;">{escape(run.get('handoff_path') or '-')}</code></td>
                        </tr>
            """)
        html_out.append("""
                    </tbody>
                </table>
        """)
    else:
        html_out.append("""
                <div style="color:#475569; padding:40px 0; text-align:center; font-style:italic; border:1px dashed rgba(255,255,255,0.05); border-radius:8px;">
                    No local-builder runs found under <code>runtime/dispatch/runs/</code>.
                </div>
        """)

    html_out.append("""
            </div>
    """)

    # ==========================================
    # TAB PANEL: HEALTH & SAFETY
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'health' else ''}">
                <h3>🏥 System Diagnostic Log</h3>
                <div style="background:rgba(59,130,246,0.08); border-left:4px solid #3b82f6; border-radius:6px; padding:14px; margin-bottom:16px;">
                    <div style="font-size:12px; color:#93c5fd; font-weight:600; margin-bottom:6px;">Phase 3.0 — Dispatch preview (dry-run only)</div>
                    <div style="font-size:11px; color:#cbd5e1; line-height:1.5;">
                        Adapter registry + command preview CLI + read-only dashboard tab.
                        No agent execution, MCP calls, or paid APIs. Live dispatch blocked per ADR-0012.
                        Design: <code>docs/PHASE_3_DESIGN_SPEC.md</code> • Blockers: <code>docs/PHASE_3_0_BLOCKERS.md</code>
                    </div>
                </div>
    """)
    
    # Distinguish ok vs empty vs error details
    if metrics["tasks_state"] == "error":
        html_out.append("""
                <div class="health-card health-err" style="background:rgba(239,68,68,0.08); border-left:4px solid #ef4444; border-radius:6px; padding:16px; margin-bottom:16px;">
                    <h4 style="margin:0 0 8px 0; color:#f87171;">✗ Task Parsing Errors Detected</h4>
        """)
        for err in metrics["task_errors"]:
            html_out.append(f'<code style="display:block; font-size:11px; margin-bottom:4px; color:#fca5a5;">- {escape(err)}</code>')
        html_out.append("</div>")
    elif metrics["tasks_state"] == "empty":
        html_out.append("""
                <div class="health-card health-ok" style="background:rgba(245,158,11,0.08); border-left:4px solid #f59e0b; border-radius:6px; padding:16px; margin-bottom:16px; color:#fbbf24;">
                    <h4 style="margin:0; color:#fbbf24;">⚡ No tasks present in the tasks directories.</h4>
                </div>
        """)
    else:
        html_out.append("""
                <div class="health-card health-ok" style="background:rgba(16,185,129,0.08); border-left:4px solid #10b981; border-radius:6px; padding:16px; margin-bottom:16px; color:#34d399;">
                    <h4 style="margin:0;">✓ All active, blocked, and done task YAML files parse successfully!</h4>
                </div>
        """)
        
    if metrics["events_state"] == "error":
        html_out.append("""
                <div class="health-card health-err" style="background:rgba(239,68,68,0.08); border-left:4px solid #ef4444; border-radius:6px; padding:16px; margin-bottom:16px;">
                    <h4 style="margin:0 0 8px 0; color:#f87171;">✗ Event Log Parsing Errors Detected</h4>
        """)
        for err in metrics["event_errors"]:
            html_out.append(f'<code style="display:block; font-size:11px; margin-bottom:4px; color:#fca5a5;">- {escape(err)}</code>')
        html_out.append("</div>")
    elif metrics["events_state"] == "empty":
        html_out.append("""
                <div class="health-card health-ok" style="background:rgba(245,158,11,0.08); border-left:4px solid #f59e0b; border-radius:6px; padding:16px; margin-bottom:16px; color:#fbbf24;">
                    <h4 style="margin:0; color:#fbbf24;">⚡ Event log file is empty.</h4>
                </div>
        """)
    else:
        html_out.append("""
                <div class="health-card health-ok" style="background:rgba(16,185,129,0.08); border-left:4px solid #10b981; border-radius:6px; padding:16px; margin-bottom:16px; color:#34d399;">
                    <h4 style="margin:0;">✓ The events log JSONL file parses successfully!</h4>
                </div>
        """)
        
    html_out.append("""
                <h3 style="margin-top:30px;">⚙️ Execution Environment</h3>
                <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:20px; border-radius:8px;">
                    <div style="margin-bottom:12px;"><b>Repository Root:</b> <code style="background:rgba(0,0,0,0.2); padding:4px; border-radius:4px;">""" + escape(ROOT_DIR.as_posix()) + """</code></div>
                    <div style="margin-bottom:12px;"><b>Active Task ID:</b> <code style="background:rgba(0,0,0,0.2); padding:4px; border-radius:4px;">T-0013</code></div>
                    <div><b>Release Role:</b> <code style="background:rgba(0,0,0,0.2); padding:4px; border-radius:4px;">Librarian & Control Plane</code></div>
                </div>
            </div>
    """)
    
    html_out.append("""
        </div>
    </div>
</body>
</html>
""")
    
    return "".join(html_out)


# ==========================================
# 3. HTTP SERVER IMPLEMENTATION
# ==========================================

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress standard terminal print logs of GET requests to keep the server output silent & clean.
        pass
        
    def do_GET(self):
        # Parse query parameters safely
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        
        page_html = generate_dashboard_html(query_params)
        self.wfile.write(page_html.encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)
        
        parsed_url = urllib.parse.urlparse(self.path)
        action = parsed_url.path
        
        error_msg = None
        success_msg = None
        redirect_url = "/?tab=kanban"
        
        try:
            if action == "/comment":
                task_id = params.get("task_id", [""])[0].strip()
                comment_text = params.get("comment", [""])[0].strip()
                agent = params.get("agent", ["human"])[0].strip()
                
                if not task_id or not comment_text:
                    raise ValueError("Task ID and Comment content are required.")
                
                append_note_event(ROOT_DIR, agent, task_id, comment_text)
                success_msg = "Comment posted successfully!"
                redirect_url = f"/?task_id={task_id}&tab=kanban"
                
            elif action == "/update_task":
                task_id = params.get("task_id", [""])[0].strip()
                status = params.get("status", [""])[0].strip()
                owner = params.get("owner", [""])[0].strip()
                reviewer = params.get("reviewer", [""])[0].strip()
                notes = params.get("notes", [""])[0].strip()
                
                if not task_id:
                    raise ValueError("Task ID is required.")
                
                update_task_file(ROOT_DIR, task_id, status, owner, reviewer, notes)
                success_msg = f"Task {task_id} reassigned/updated successfully!"
                redirect_url = f"/?task_id={task_id}&tab=kanban"
                
            elif action == "/create_task":
                title = params.get("title", [""])[0].strip()
                owner = params.get("owner", ["unassigned"])[0].strip()
                reviewer = params.get("reviewer", ["unassigned"])[0].strip()
                priority = params.get("priority", ["medium"])[0].strip()
                risk_level = params.get("risk_level", ["low"])[0].strip()
                phase = params.get("phase", ["1.6"])[0].strip()
                objective = params.get("objective", [""])[0].strip()
                context = params.get("context", [""])[0].strip()
                goals_raw = params.get("goals", [""])[0].strip()
                acceptance_raw = params.get("acceptance", [""])[0].strip()
                
                if not title or not objective or not acceptance_raw:
                    raise ValueError("Title, Objective, and Acceptance Criteria are required.")
                
                goals = [g.strip() for g in goals_raw.split("\n") if g.strip()]
                acceptance = [a.strip() for a in acceptance_raw.split("\n") if a.strip()]
                
                new_id = create_task_file(
                    ROOT_DIR, title, owner, reviewer, objective,
                    context, phase, priority, risk_level, goals, acceptance
                )
                success_msg = f"Task {new_id} created successfully!"
                redirect_url = f"/?task_id={new_id}&tab=kanban"
                
            else:
                raise ValueError(f"Unknown POST action: {action}")
                
        except Exception as e:
            error_msg = str(e)
            # Retain tab state on error
            if action == "/create_task":
                redirect_url = "/?tab=create_task"
            elif action == "/comment" or action == "/update_task":
                task_id = params.get("task_id", [None])[0]
                redirect_url = f"/?task_id={task_id}&tab=kanban" if task_id else "/?tab=kanban"
                
        # Send 303 Redirect back
        parsed_redirect = urllib.parse.urlparse(redirect_url)
        redirect_params = urllib.parse.parse_qs(parsed_redirect.query)
        if error_msg:
            redirect_params["error"] = [error_msg]
        if success_msg:
            redirect_params["success"] = [success_msg]
            
        new_query = urllib.parse.urlencode(redirect_params, doseq=True)
        new_redirect = urllib.parse.urlunparse((
            parsed_redirect.scheme,
            parsed_redirect.netloc,
            parsed_redirect.path,
            parsed_redirect.params,
            new_query,
            parsed_redirect.fragment
        ))
        
        self.send_response(303)
        self.send_header("Location", new_redirect)
        self.end_headers()


def serve_dashboard(port: int = 8501) -> None:
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), DashboardHandler) as httpd:
        print(f"Agentic OS Local Dashboard active at http://localhost:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down Dashboard server.")


if __name__ == "__main__":
    serve_dashboard(8501)
