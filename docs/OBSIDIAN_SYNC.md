# Obsidian Vault Sync (Phase 2.3)

Phase 2.3 adds a **safe, local-first, one-way sync** from the Agentic OS repository
into an Obsidian vault. The repo remains the operational source of truth; Obsidian
is a human-readable memory mirror.

## One-Way Model

| Direction | Supported |
|-----------|-----------|
| Repo → Vault | Yes (this phase) |
| Vault → Repo | No (future) |

Obsidian notes are **never** read back as instructions. No bidirectional sync.
No Obsidian API or plugin required — direct filesystem writes only.

## Vault Folder Structure

All synced content lives under `{vault_path}/AgenticOS/`:

```
AgenticOS/
  00_Index.md
  01_Projects/agentic-os/
    Overview.md
    Current State.md
    Roadmap.md
    Decisions/
  02_Tasks/{active,done,blocked}/
  03_Teams/
  03_Roles/
  04_Skills/
  05_MCPs/
  06_Handoffs/
  07_Logs/
  08_Memory/
  09_Reviews/
  .sync/last_sync_report.json
```

## Configuration

Edit `memory/obsidian_mapping.yaml` locally:

```yaml
vault_path: null          # set locally; do not commit personal paths
sync_enabled: false
dry_run_default: true
```

When `sync_enabled` is `false`, real sync requires an explicit `--vault` argument.

## Dry-Run

```bash
python scripts/sync_obsidian.py --dry-run
python scripts/sync_obsidian.py --dry-run --json
```

Calculates planned notes, prints summary, **writes no files**.

## Real Sync

```bash
python scripts/sync_obsidian.py --vault "C:\path\to\vault"
python scripts/sync_obsidian.py --vault "C:\path\to\vault" --json
```

Creates folders as needed, writes Markdown notes, and saves a sync report at
`AgenticOS/.sync/last_sync_report.json` inside the vault.

## What Gets Synced

| Source | Vault destination |
|--------|-------------------|
| `tasks/{active,done,blocked}/*.yaml` | `02_Tasks/.../*.md` |
| `handoffs/*.md` | `06_Handoffs/` |
| `decisions/*.md` | `01_Projects/agentic-os/Decisions/` |
| `logs/agent-events.jsonl` | `07_Logs/Latest Events.md`, `Event Summary.md` |
| `skills/registry.yaml` | `04_Skills/<id>.md` |
| `mcps/registry.yaml` | `05_MCPs/<id>.md` |
| `teams/registry.yaml` | `03_Teams/<id>.md` |
| `roles/registry.yaml` | `03_Roles/<id>.md` |
| Derived summary | `01_Projects/agentic-os/Current State.md` |

## Safety Rules

1. **Never delete** user-created Obsidian notes.
2. **Never write** outside the configured vault path.
3. **Only overwrite** files under `AgenticOS/` that this sync owns.
4. **Block path traversal** in vault paths and relative note paths.
5. **Sanitize filenames** for Obsidian compatibility.
6. **Default dry-run** when `vault_path` is not configured.
7. **No secrets** — `.env` and key files are excluded.
8. **No Obsidian execution** — vault can be closed.

## Dashboard

```bash
python dashboard/app.py
```

Open `/?tab=obsidian` for read-only sync status, planned note count, and CLI hints.
The dashboard does **not** trigger sync in Phase 2.3.

## Limitations

- One-way only; vault edits are not imported.
- No Obsidian Local REST MCP integration yet (metadata exists in MCP registry).
- No automatic scheduled sync.
- `vault_path` must be configured locally for last-sync status in dashboard.
- Memory seed notes (`08_Memory/`) are placeholders, not live librarian output.

## Future Work

- **Bidirectional sync** with strict write rules and human approval.
- **Obsidian Local REST MCP** for optional API-based sync.
- **LangGraph orchestrator** (Phase 2.4) may trigger sync after task completion.

## Verification

```bash
python -m unittest tests.test_obsidian_sync
python -m unittest
python scripts/validate.py
```