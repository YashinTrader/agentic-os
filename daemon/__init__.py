"""Agentic OS runtime daemon — local CLI/tool discovery layer."""

from daemon.cli_discovery import discover_clis, run_discovery
from daemon.registry_writer import append_discovery_event, write_daemon_status, write_inventory

__all__ = [
    "discover_clis",
    "run_discovery",
    "write_inventory",
    "write_daemon_status",
    "append_discovery_event",
]