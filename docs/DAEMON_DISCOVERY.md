# Daemon Discovery (Phase 2.0)

Phase 2.0 introduces a **local runtime discovery daemon** that observes which
developer and agent CLIs are installed on the host machine and writes a
machine-readable inventory for the Agentic OS control plane.

## What the Daemon Does

1. **Detects CLIs on PATH** using `shutil.which` (stdlib).
2. **Probes versions safely** with read-only subprocess calls:
   - `timeout` enforced (default 5 seconds)
   - `shell=False`
   - no network calls
   - no authentication
   - no agent execution
3. **Writes inventory artifacts:**
   - `runtime/registry/cli_inventory.yaml`
   - `runtime/status/daemon_status.json`
4. **Appends an audit event** to `logs/agent-events.jsonl` using the existing
   ADR-0004 `note` event type.
5. **Exposes inventory in the dashboard** via the **Agents / Tools** tab.

## What the Daemon Does Not Do

- Launch Codex, Claude, Gemini, Cursor, or any other agent
- Connect to paid APIs or read secrets
- Modify tasks, handoffs, ADRs, or the file-based protocol
- Replace Git-as-message-bus
- Add databases, LangGraph, Obsidian sync, or MCP execution
- Control agents autonomously

The daemon is **observe and report only**.

## Running the Daemon

From the repository root:

```bash
python -m daemon.daemon --once
```

This runs discovery once, writes runtime artifacts, appends a log event, and exits.

Optional watch mode (repeat on an interval, interruptible with Ctrl+C):

```bash
python -m daemon.daemon --watch --interval 60
```

Custom repository root:

```bash
python -m daemon.daemon --root /path/to/agentic-os --once
```

## Inventory File Structure

`runtime/registry/cli_inventory.yaml`:

```yaml
schema_version: "1.0"
generated_at: 2026-06-07T12:00:00Z
discovery_method: local_path_and_read_only_version_probe
summary:
  total: 14
  available: 8
  missing: 6
tools:
  - id: git
    display_name: Git
    available: true
    path: /usr/bin/git
    version: "2.43.0"
    version_command_used: git --version
    detection_method: shutil.which
    last_checked: 2026-06-07T12:00:00Z
    notes: null
```

Each tool entry includes:

| Field | Description |
|-------|-------------|
| `id` | Stable identifier |
| `display_name` | Human-readable label |
| `available` | Whether the CLI was found on PATH |
| `path` | Resolved binary path, or null |
| `version` | Parsed version string, or null |
| `version_command_used` | Command attempted for version probe |
| `detection_method` | How presence was detected |
| `last_checked` | UTC timestamp of last probe |
| `notes` | Explanation when version is unknown or CLI is missing |

## Daemon Status File

`runtime/status/daemon_status.json`:

```json
{
  "schema_version": "1.0",
  "daemon": "agentic-os-cli-discovery",
  "mode": "once",
  "status": "ok",
  "started_at": "2026-06-07T12:00:00Z",
  "finished_at": "2026-06-07T12:00:01Z",
  "last_run_at": "2026-06-07T12:00:01Z",
  "inventory_path": "runtime/registry/cli_inventory.yaml",
  "summary": { "total": 14, "available": 8, "missing": 6 },
  "errors": []
}
```

## Safety Guarantees

- **No shell execution** — subprocess calls use explicit argument lists
- **Bounded timeouts** — version probes cannot hang indefinitely
- **Read-only probes** — only `--version`, `-V`, or `version` style flags
- **Graceful degradation** — missing CLIs and failed version probes never crash the daemon
- **No secrets** — daemon does not read `.env`, credentials, or API keys
- **No network** — purely local filesystem and PATH inspection

## Detected Tools (Minimum Set)

| ID | Display Name |
|----|--------------|
| `git` | Git |
| `gh` | GitHub CLI |
| `python` | Python |
| `node` | Node.js |
| `npm` | npm |
| `uv` | uv |
| `streamlit` | Streamlit |
| `ollama` | Ollama |
| `codex` | Codex CLI |
| `claude` | Claude Code |
| `gemini` | Gemini CLI |
| `cursor` | Cursor CLI |
| `opencode` | OpenCode |
| `aider` | Aider |

## Known Limitations

1. **PATH-dependent** — only tools visible on the current user's PATH are detected.
2. **Version uncertainty** — AI agent CLIs may not expose stable `--version` flags;
   version may be `null` with an explanatory note.
3. **No capability probing** — presence does not imply the tool is configured or licensed.
4. **Single-host view** — inventory reflects the machine where the daemon ran.
5. **Watch mode is optional** — not required for Phase 2.0 acceptance.
6. **Dashboard is read-only for inventory** — the tab does not trigger discovery or launch tools.

## Dashboard Integration

After running the daemon, open the dashboard:

```bash
python dashboard/app.py
```

Navigate to **Agents / Tools** (`/?tab=agents_tools`) to view:

- per-tool availability, version, path, and notes
- health summary: total / available / missing tools
- last daemon run timestamp and status

## Verification

```bash
python -m daemon.daemon --once
python -m unittest tests.test_cli_discovery
python -m unittest
python scripts/validate.py
```

## Next Step After Daemon Discovery

**Phase 2.1 — Skills + MCP Registry**

Extend the runtime layer to inventory locally configured skills and MCP server
definitions (read-only registry, still no execution). The CLI discovery daemon
becomes one surface in a broader `runtime/registry/` tree.