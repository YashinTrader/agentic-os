# Agentic OS Runtime Daemon (Phase 2.0)

Local, read-only discovery layer that inventories installed CLIs and agent tools
on the host machine and writes machine-readable artifacts under `runtime/`.

## What It Does

- Detects common developer and agent CLIs via `shutil.which`
- Probes versions with safe, read-only subprocess calls (timeout, no shell)
- Writes `runtime/registry/cli_inventory.yaml`
- Writes `runtime/status/daemon_status.json`
- Appends a `note` event to `logs/agent-events.jsonl`

## What It Does Not Do

- Launch or control agents
- Call paid APIs or authenticate anywhere
- Execute agent workloads
- Modify tasks, handoffs, or ADRs
- Replace the file-based protocol

## Usage

From the repository root:

```bash
python -m daemon.daemon --once
```

Optional watch mode:

```bash
python -m daemon.daemon --watch --interval 60
```

## Outputs

| File | Purpose |
|------|---------|
| `runtime/registry/cli_inventory.yaml` | Full tool inventory |
| `runtime/status/daemon_status.json` | Last daemon run metadata |
| `logs/agent-events.jsonl` | Append-only audit trail entry |

See `docs/DAEMON_DISCOVERY.md` for the full protocol and safety guarantees.