# Agentic OS Kanban Dashboard (Phase 1.6)

A lightweight, zero-dependency, local-first read-only web dashboard for observing the Agentic OS control plane in real-time. Built entirely with standard library Python utilities and `pyyaml`, it parses Schema v2 task files, ADR-0004 standard event logs, open handoffs, and architectural decision records (ADRs).

---

## Features

1. **📋 Dynamic Kanban Board:** Displays all repository tasks across five columns (`ready`, `in_progress`, `review`, `blocked`, `done`) in real-time. Clicking on a card launches a deep-inspection details panel of all Schema v2 fields (`goals`, `non_goals`, `context`, `acceptance`, `requires_human_approval`, `human_approval_checklist`, `notes`, `created_at`, `updated_at`, `created_by`, `reviewer`, `priority`).
2. **📜 Event Timeline:** Renders the events log (`logs/agent-events.jsonl`) following the **ADR-0004 standard vocabulary**. It reverses events to show the newest 30 events first and adds live filters for agents and tasks. It also features non-fatal warning highlights for non-compliant event types.
3. **📑 Handoffs & ADRs Reader:** Lists all Markdown handoffs (`handoffs/*.md`) and architectural decision records (`decisions/ADR-*.md`). Scans the first 10 lines of ADRs to detect status (`accepted` | `proposed` | `rejected`) case-insensitively and renders them.
4. **Execution Runs:** Displays recent local-builder artifacts from `runtime/dispatch/runs/`, including task ID, adapter, route, status, timestamps, worktree path, verification status, blocked reasons, and handoff path. Missing or malformed runtime files are shown as non-fatal warnings.
5. **🏥 System Health Diagnostic Panel:** Sidebar health indicator distinguishing three states per surface: **OK** (green), **EMPTY** (yellow), and **ERROR** (red), complete with error stack traces for YAML parsing failures.

---

## Explicit Non-Goals

To maintain the strict file-based safety and local-first architecture of Phase 1, the dashboard explicitly does **NOT** do the following:
* **No Write Operations:** It performs zero writes, no file mutations, and no shell subprocess execution to call CLI helper scripts.
* **No Execution Controls:** The execution-runs page is observational only. It does not execute, retry, approve, merge, push, or deploy local-builder runs.
* **No Database or Daemon:** Uses the Git repository files directly as the single source of truth. No server-side persistence or daemon is added.
* **No Authentication:** It is designed for single-user local-only execution. No user accounts, multi-tenant state, or server state exist.
* **No New Dependencies:** It introduces absolutely zero third-party dependencies beyond the pre-existing `pyyaml` (in `requirements.txt`).
* **No Token or Usage Monitoring:** Cost and budget tracking are deferred to Phase 2.
* **No Dependency Graph:** Visually drawing task blockages is a Phase 2 item.

---

## Getting Started

### 1. Install PyYAML
The only required package is `pyyaml` (which is already pinned in the root `requirements.txt`):
```bash
pip install -r requirements.txt
```

### 2. Launch Dashboard
Run the standard Python application:
```bash
python dashboard/app.py
```
Open **`http://localhost:8501/`** in your browser to view the real-time control plane!

---

## Known Limitations
* **Local-only:** Built using standard library `http.server.BaseHTTPRequestHandler`. Intended for local single-user read-only operation.
* **Single-threaded:** Uses standard Python blocking server (ideal for local single-user, avoids concurrent socket complexities).
