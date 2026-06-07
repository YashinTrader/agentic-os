"""One-way sync from Agentic OS repo into an Obsidian vault."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from integrations.obsidian.mapping import load_mapping, output_folders, vault_root_folder
from integrations.obsidian.vault_writer import VaultWriter, sanitize_filename, utc_now_iso


@dataclass
class NotePlan:
    relative_path: str
    content: str
    source: str


@dataclass
class SyncReport:
    dry_run: bool
    vault_path: str | None
    notes_planned: int = 0
    notes_written: int = 0
    folders_created: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    report_path: str | None = None
    synced_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "vault_path": self.vault_path,
            "synced_at": self.synced_at,
            "notes_planned": self.notes_planned,
            "notes_written": self.notes_written,
            "folders_created": sorted(self.folders_created),
            "warnings": self.warnings,
            "errors": self.errors,
            "report_path": self.report_path,
        }


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_list(items: list[Any]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def task_to_markdown(task: dict[str, Any], folder_label: str, synced_at: str) -> str:
    task_id = str(task.get("id", "unknown"))
    fm = _frontmatter(
        {
            "type": "task",
            "id": task_id,
            "status": task.get("status", "unknown"),
            "owner": task.get("owner", ""),
            "risk_level": task.get("risk_level", ""),
            "approval_level": task.get("approval_level", task.get("approval", "")),
            "source": "agentic-os",
            "synced_at": synced_at,
        }
    )
    acceptance = task.get("acceptance", task.get("acceptance_criteria", []))
    if isinstance(acceptance, str):
        acceptance = [acceptance]
    related = task.get("related_decisions", [])
    links = [f"[[{task_id}]]", "[[Current State]]"]
    if related:
        links.extend(f"[[{d}]]" for d in related if isinstance(d, str))
    body = f"""# {task.get('title', task_id)}

## Objective
{task.get('objective', task.get('context', '')).strip()}

## Status
- Folder: `{folder_label}`
- Owner: {task.get('owner', '—')}
- Reviewer: {task.get('reviewer', '—')}
- Priority: {task.get('priority', '—')}
- Phase: {task.get('phase', '—')}

## Acceptance
{_yaml_list(acceptance if isinstance(acceptance, list) else [])}

## Goals
{_yaml_list(task.get('goals', []) if isinstance(task.get('goals'), list) else [])}

## Notes
{task.get('notes', '—')}

## Related
{', '.join(links)}
"""
    return f"{fm}\n\n{body.strip()}\n"


def registry_item_to_markdown(
    item_type: str,
    item: dict[str, Any],
    synced_at: str,
) -> str:
    item_id = str(item.get("id", "unknown"))
    fm = _frontmatter(
        {
            "type": item_type,
            "id": item_id,
            "source": "agentic-os",
            "synced_at": synced_at,
        }
    )
    if item_type == "skill":
        body = f"""# {item.get('name', item_id)}

## Description
{item.get('description', '')}

## Metadata
- Category: {item.get('category', '—')}
- Status: {item.get('status', '—')}
- Risk: {item.get('risk_level', '—')}
- Approval: {item.get('approval_level', '—')}

## Allowed Agents
{_yaml_list(item.get('allowed_agents', []))}

## Tags
{_yaml_list(item.get('tags', []))}

## Related
[[Current State]]
"""
    elif item_type == "mcp":
        body = f"""# {item.get('name', item_id)}

## Description
{item.get('description', '')}

## Metadata
- Status: {item.get('status', '—')}
- Transport: {item.get('transport', '—')}
- Risk: {item.get('risk_level', '—')}
- Approval: {item.get('approval_level', '—')}

## Allowed Agents
{_yaml_list(item.get('allowed_agents', []))}

## Related
[[Current State]]
"""
    elif item_type == "team":
        members = item.get("members", [])
        member_lines = []
        if isinstance(members, list):
            for m in members:
                if isinstance(m, dict):
                    member_lines.append(
                        f"- {m.get('agent')} ({m.get('role')}) — skills: {', '.join(m.get('skills', [])) or '—'}"
                    )
        body = f"""# {item.get('name', item_id)}

## Purpose
{item.get('purpose', item.get('description', ''))}

## Status
{item.get('status', '—')}

## Members
{chr(10).join(member_lines) if member_lines else '- (none)'}

## Required Skills
{_yaml_list(item.get('required_skills', []))}

## Related
[[Current State]]
"""
    elif item_type == "role":
        body = f"""# {item.get('name', item_id)}

## Description
{item.get('description', '')}

## Governance
- Risk: {item.get('risk_level', '—')}
- Approval: {item.get('approval_level', '—')}
- can_delegate: {item.get('can_delegate')}
- can_review: {item.get('can_review')}
- can_execute: {item.get('can_execute')}

## Allowed Agents
{_yaml_list(item.get('allowed_agents', []))}

## Required Skills
{_yaml_list(item.get('required_skills', []))}

## Related
[[Current State]]
"""
    else:
        body = f"# {item_id}\n\n{json.dumps(item, indent=2)}\n"
    return f"{fm}\n\n{body.strip()}\n"


def _load_yaml_tasks(repo_root: Path, subfolder: str) -> list[tuple[str, dict[str, Any]]]:
    folder = repo_root / "tasks" / subfolder
    results: list[tuple[str, dict[str, Any]]] = []
    if not folder.exists():
        return results
    for path in sorted(folder.glob("*.yaml")):
        if path.name == "EXAMPLE.yaml":
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                results.append((subfolder, data))
        except Exception:
            continue
    return results


def _load_registry_list(repo_root: Path, rel_path: str, key: str) -> list[dict[str, Any]]:
    path = repo_root / rel_path
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return [x for x in data[key] if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _parse_events(repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    log_path = repo_root / "logs" / "agent-events.jsonl"
    events: list[dict[str, Any]] = []
    if not log_path.exists():
        warnings.append("logs/agent-events.jsonl not found; skipping event details")
        return events, warnings
    for line_no, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                events.append(row)
        except json.JSONDecodeError:
            warnings.append(f"logs/agent-events.jsonl:{line_no}: invalid JSON line skipped")
    return events, warnings


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or "unknown")


def build_log_notes(events: list[dict[str, Any]], synced_at: str) -> tuple[str, str]:
    latest = sorted(events, key=lambda e: str(e.get("ts", "")), reverse=True)[:50]
    latest_lines = []
    for ev in latest:
        latest_lines.append(
            f"- `{ev.get('ts', '—')}` **{ev.get('agent', '—')}** / {ev.get('task', '—')} "
            f"— {_event_type(ev)} — {ev.get('detail', '')}"
        )
    latest_md = f"""---
type: log
source: agentic-os
synced_at: {synced_at}
---

# Latest Events

Showing newest {len(latest)} events.

{chr(10).join(latest_lines) if latest_lines else '- (no events)'}

## Related
[[Current State]]
[[Event Summary]]
"""

    type_counts = Counter(_event_type(e) for e in events)
    agent_counts = Counter(str(e.get("agent", "unknown")) for e in events)
    task_counts = Counter(str(e.get("task", "unknown")) for e in events)

    def counter_lines(counter: Counter) -> str:
        if not counter:
            return "- (none)"
        return "\n".join(f"- {k}: {v}" for k, v in counter.most_common())

    summary_md = f"""---
type: log-summary
source: agentic-os
synced_at: {synced_at}
---

# Event Summary

Total events: {len(events)}

## By Event Type
{counter_lines(type_counts)}

## By Agent
{counter_lines(agent_counts)}

## By Task
{counter_lines(task_counts)}

## Related
[[Current State]]
[[Latest Events]]
"""
    return latest_md, summary_md


def build_current_state(repo_root: Path, synced_at: str) -> str:
    active = len(_load_yaml_tasks(repo_root, "active"))
    done = len(_load_yaml_tasks(repo_root, "done"))
    blocked = len(_load_yaml_tasks(repo_root, "blocked"))
    skills = len(_load_registry_list(repo_root, "skills/registry.yaml", "skills"))
    mcps = len(_load_registry_list(repo_root, "mcps/registry.yaml", "mcps"))
    teams = len(_load_registry_list(repo_root, "teams/registry.yaml", "teams"))
    roles = len(_load_registry_list(repo_root, "roles/registry.yaml", "roles"))

    cli_count = 0
    cli_path = repo_root / "runtime" / "registry" / "cli_inventory.yaml"
    if cli_path.exists():
        try:
            cli_data = yaml.safe_load(cli_path.read_text(encoding="utf-8"))
            if isinstance(cli_data, dict):
                tools = cli_data.get("tools", cli_data.get("clis", []))
                if isinstance(tools, list):
                    cli_count = len(tools)
        except Exception:
            pass

    events, _ = _parse_events(repo_root)
    last_ts = max((str(e.get("ts", "")) for e in events), default="—")

    handoffs_dir = repo_root / "handoffs"
    latest_handoff = "—"
    if handoffs_dir.exists():
        md_files = sorted(
            [p for p in handoffs_dir.glob("*.md") if p.name != "README.md"],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if md_files:
            latest_handoff = md_files[0].stem

    return f"""---
type: current-state
source: agentic-os
synced_at: {synced_at}
---

# Current State

## Task Counts
- Active: {active}
- Done: {done}
- Blocked: {blocked}

## Registries
- Skills: {skills}
- MCPs: {mcps}
- Teams: {teams}
- Roles: {roles}
- CLI tools (inventory): {cli_count if cli_count else '—'}

## Activity
- Last event timestamp: {last_ts}
- Latest handoff: [[{latest_handoff}]]

## Related
[[00_Index]]
"""


def collect_notes(repo_root: Path, mapping: dict[str, Any] | None = None) -> tuple[list[NotePlan], list[str]]:
    mapping = mapping or load_mapping(repo_root)
    folders = output_folders(mapping)
    root_name = vault_root_folder(mapping)
    synced_at = utc_now_iso()
    warnings: list[str] = []
    notes: list[NotePlan] = []
    include = set(mapping.get("include_sections", []))

    def add(rel_folder: str, filename: str, content: str, source: str) -> None:
        if rel_folder:
            rel = f"{rel_folder}/{filename}".replace("\\", "/")
        else:
            rel = filename
        notes.append(NotePlan(relative_path=rel, content=content, source=source))

    if "index" in include:
        index_md = f"""---
type: index
source: agentic-os
synced_at: {synced_at}
---

# Agentic OS Vault Index

One-way mirror from the Agentic OS repository.

## Navigation
- [[Current State]]
- [[Overview]]
- [[Roadmap]]

## Folders
- Tasks: `02_Tasks/`
- Handoffs: `06_Handoffs/`
- Skills: `04_Skills/`
- Teams: `03_Teams/`
"""
        add("", "00_Index.md", index_md, "index")

    project_root = folders.get("project_root", "01_Projects/agentic-os")
    if "current_state" in include:
        add(project_root, "Current State.md", build_current_state(repo_root, synced_at), "current_state")
        add(project_root, "Overview.md", f"# Agentic OS\n\nProject: {mapping.get('project_name', 'agentic-os')}\n\nSee [[Current State]].\n", "overview")
        add(project_root, "Roadmap.md", "# Roadmap\n\nSee repo `docs/` and [[Current State]].\n", "roadmap")

    task_map = {
        "active": folders.get("tasks_active", "02_Tasks/active"),
        "done": folders.get("tasks_done", "02_Tasks/done"),
        "blocked": folders.get("tasks_blocked", "02_Tasks/blocked"),
    }
    if "tasks" in include:
        for subfolder, rel_folder in task_map.items():
            for folder_label, task in _load_yaml_tasks(repo_root, subfolder):
                task_id = sanitize_filename(str(task.get("id", "task")))
                add(rel_folder, f"{task_id}.md", task_to_markdown(task, folder_label, synced_at), f"tasks/{subfolder}")

    if "handoffs" in include:
        handoffs_dir = repo_root / "handoffs"
        rel_handoffs = folders.get("handoffs", "06_Handoffs")
        if handoffs_dir.exists():
            for path in sorted(handoffs_dir.glob("*.md")):
                if path.name == "README.md":
                    continue
                content = path.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    content = f"---\ntype: handoff\nsource: agentic-os\nsynced_at: {synced_at}\n---\n\n{content}"
                add(rel_handoffs, path.name, content, "handoffs")

    if "decisions" in include:
        decisions_dir = repo_root / "decisions"
        rel_decisions = folders.get("decisions", f"{project_root}/Decisions")
        if decisions_dir.exists():
            for path in sorted(decisions_dir.glob("*.md")):
                if path.name == "INDEX.md":
                    continue
                content = path.read_text(encoding="utf-8")
                add(rel_decisions, path.name, content, "decisions")

    if "logs" in include:
        events, log_warnings = _parse_events(repo_root)
        warnings.extend(log_warnings)
        rel_logs = folders.get("logs", "07_Logs")
        latest_md, summary_md = build_log_notes(events, synced_at)
        add(rel_logs, "Latest Events.md", latest_md, "logs/latest")
        add(rel_logs, "Event Summary.md", summary_md, "logs/summary")

    if "skills" in include:
        rel_skills = folders.get("skills", "04_Skills")
        for skill in _load_registry_list(repo_root, "skills/registry.yaml", "skills"):
            sid = sanitize_filename(str(skill.get("id", "skill")))
            add(rel_skills, f"{sid}.md", registry_item_to_markdown("skill", skill, synced_at), "skills")

    if "mcps" in include:
        rel_mcps = folders.get("mcps", "05_MCPs")
        for mcp in _load_registry_list(repo_root, "mcps/registry.yaml", "mcps"):
            mid = sanitize_filename(str(mcp.get("id", "mcp")))
            add(rel_mcps, f"{mid}.md", registry_item_to_markdown("mcp", mcp, synced_at), "mcps")

    if "teams" in include:
        rel_teams = folders.get("teams", "03_Teams")
        for team in _load_registry_list(repo_root, "teams/registry.yaml", "teams"):
            tid = sanitize_filename(str(team.get("id", "team")))
            add(rel_teams, f"{tid}.md", registry_item_to_markdown("team", team, synced_at), "teams")

    if "roles" in include:
        rel_roles = folders.get("roles", "03_Roles")
        for role in _load_registry_list(repo_root, "roles/registry.yaml", "roles"):
            rid = sanitize_filename(str(role.get("id", "role")))
            add(rel_roles, f"{rid}.md", registry_item_to_markdown("role", role, synced_at), "roles")

    memory_folder = folders.get("memory", "08_Memory")
    for seed in ("Facts.md", "Failures.md", "Patterns.md", "Open Questions.md"):
        add(memory_folder, seed, f"# {seed.replace('.md', '')}\n\nSeed note for future librarian workflows.\n\nSee [[Current State]].\n", "memory-seed")

    return notes, warnings


def run_sync(
    repo_root: Path,
    vault_path: Path | None,
    *,
    dry_run: bool = True,
    mapping: dict[str, Any] | None = None,
) -> SyncReport:
    mapping = mapping or load_mapping(repo_root)
    root_folder = vault_root_folder(mapping)
    notes, collect_warnings = collect_notes(repo_root, mapping)

    report = SyncReport(
        dry_run=dry_run,
        vault_path=str(vault_path) if vault_path else None,
        notes_planned=len(notes),
        warnings=list(collect_warnings),
    )

    if vault_path is None:
        return report

    writer = VaultWriter(vault_path=vault_path, vault_root_folder=root_folder, dry_run=dry_run)
    for note in notes:
        try:
            writer.write_note(note.relative_path, note.content)
        except ValueError as exc:
            report.errors.append(f"{note.relative_path}: {exc}")

    report.folders_created = sorted(writer.folders_created)
    report.notes_written = len(writer.notes_written) if not dry_run else 0
    report.warnings.extend(writer.warnings)

    if not dry_run and not report.errors:
        last_sync_rel = str(mapping.get("last_sync_file", f"{root_folder}/.sync/last_sync_report.json"))
        if last_sync_rel.startswith(f"{root_folder}/"):
            report_rel = last_sync_rel[len(root_folder) + 1 :]
        else:
            report_rel = ".sync/last_sync_report.json"
        report.report_path = str(vault_path / last_sync_rel)
        writer.write_report(report_rel, report.to_dict())

    return report