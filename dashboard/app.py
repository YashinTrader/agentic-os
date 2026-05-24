from __future__ import annotations

import html
import http.server
import json
import socketserver
import sys
import urllib.parse
from pathlib import Path

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
    
    # 1. State extraction
    selected_task_id = query_params.get("task_id", [None])[0]
    filter_agent = query_params.get("agent", [""])[0].strip()
    filter_task = query_params.get("task", [""])[0].strip()
    read_file_path = query_params.get("read_file", [None])[0]
    
    # Determine default active tab based on parameters
    active_tab = "kanban"
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
            Antigravity Dashboard • Phase 2.0
        </div>
    </div>
    """)
    
    # 3. RENDER MAIN PANELS WITH TABS
    html_out.append("""
    <div class="main-content">
        <div class="tabs-container">
            <div class="tab-headers">
    """)
    
    # Render Tab Headers
    html_out.append(f"""
                <a href="/?tab=kanban" class="tab-link {'active' if active_tab == 'kanban' else ''}">📋 Kanban Board</a>
                <a href="/?tab=events" class="tab-link {'active' if active_tab == 'events' else ''}">📜 System Events</a>
                <a href="/?tab=handoffs" class="tab-link {'active' if active_tab == 'handoffs' else ''}">📑 Handoffs & ADRs</a>
                <a href="/?tab=health" class="tab-link {'active' if active_tab == 'health' else ''}">🏥 Health Panel</a>
    """)
    
    html_out.append("""
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
                        </div>
                        
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
                            
                            <div style="font-size:10px; color:#475569; margin-top:16px;">
                                Created: {escape(selected_task['created_at'])}<br/>
                                Updated: {escape(selected_task['updated_at'])}
                            </div>
                        </div>
                    </div>
                </div>
            """)
            
    html_out.append("""
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
    # TAB PANEL: HEALTH & SAFETY
    # ==========================================
    html_out.append(f"""
            <div class="tab-panel {'active' if active_tab == 'health' else ''}">
                <h3>🏥 System Diagnostic Log</h3>
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
