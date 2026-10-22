#!/usr/bin/env python3
"""Audited local stop and maintenance controls for the layer supervisor."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
import subprocess
import time
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.atomic_io import atomic_write_json
from orchestrator.layer_heartbeat import read_heartbeat, timestamp
from orchestrator.supervisor_control import control_dir, file_lock, identity_state, force_recorded_tree, is_legacy_status, legacy_process_blockers
from root_paths import resolve_state_root


def stop(root: Path, actor: str, reason: str, timeout: float = 90,
         maintenance: str | None = None, *, request_stop: bool = True) -> int:
    directory = control_dir(root)
    token = uuid.uuid4().hex
    audit = {"requester": actor, "reason": reason, "token": token, "at": timestamp(),
             "maintenance": maintenance}
    audit_path = directory / "audit" / f"{token}.json"

    def finish(code, message):
        audit.update(exit_code=code, outcome=message, finished_at=timestamp())
        atomic_write_json(audit_path, audit)
        print(message, flush=True)
        return code

    try:
        # Serialize operators, but do not block the supervisor's loop/shutdown.
        with file_lock(directory / "operator.lock"):
            with file_lock(directory / "control.lock"):
                atomic_write_json(audit_path, audit)
                if maintenance == "on":
                    atomic_write_json(directory / "maintenance.json", audit)
                elif maintenance == "off":
                    (directory / "maintenance.json").unlink(missing_ok=True)
                if not request_stop:
                    return finish(0, f"maintenance mode {maintenance}")
                status = read_heartbeat(directory / "status.json")
                if not status or identity_state(status) in {"reused", "unknown"}:
                    return finish(2, "refused: missing, reused or unverifiable root PID/start time")
                audit["root"] = {key: status.get(key) for key in
                                 ("pid", "process_start_time", "instance_token", "process_identity")}
                request = {**audit["root"], **{key: audit[key] for key in
                           ("requester", "reason", "token", "at")}}
                atomic_write_json(directory / "stop_request.json", request)
                audit["request"] = request
                atomic_write_json(audit_path, audit)
            records = {}

            def tree_states():
                current = read_heartbeat(directory / "status.json")
                if (current.get("pid"), current.get("process_start_time")) == (
                        status.get("pid"), status.get("process_start_time")):
                    sources = [status, current]
                else:
                    sources = [status]
                for source in sources:
                    if (not isinstance(source.get("recorded_children", []), list)
                            or not isinstance(source.get("children", {}), dict)):
                        raise ValueError("invalid recorded child identities")
                    for record in [source, *source.get("recorded_children", []),
                                   *source.get("children", {}).values()]:
                        if not isinstance(record, dict):
                            raise ValueError("invalid recorded process identity")
                        if record.get("pid") is not None:
                            if (type(record["pid"]) is not int
                                    or not isinstance(record.get("process_start_time"), str)):
                                raise ValueError("incomplete recorded process identity")
                            records[(record.get("pid"), record.get("process_start_time"))] = record
                states = [identity_state(record) for record in records.values()]
                audit["verified_processes"] = [
                    {"pid": record.get("pid"), "process_start_time": record.get("process_start_time"),
                     "state": state} for record, state in zip(records.values(), states)]
                return states

            deadline = time.monotonic() + timeout
            while True:
                states = tree_states()
                if "unknown" in states:
                    return finish(2, "refused: process identity cannot be verified")
                if all(state in {"gone", "reused"} for state in states):
                    latest = read_heartbeat(directory / "status.json")
                    acknowledged = latest.get("stop_request") or {}
                    if not isinstance(acknowledged, dict):
                        raise ValueError("invalid stop acknowledgement")
                    if (latest.get("instance_token") == status.get("instance_token")
                            and latest.get("state") == "stopped_by_request"
                            and acknowledged.get("token") == token):
                        return finish(0, "graceful: recorded supervisor tree is gone")
                    if status.get("state") in {"stopped", "stopped_by_request"}:
                        return finish(0, "graceful: recorded supervisor tree was already stopped")
                    if time.monotonic() >= deadline:
                        return finish(2, "failed: tree exited without acknowledging this stop request")
                if time.monotonic() >= deadline:
                    break
                time.sleep(.1)
            if identity_state(status) != "live":
                return finish(2, "refused: root no longer matches; surviving children cannot be targeted")
            audit.update(forced=True, forced_at=timestamp())
            atomic_write_json(audit_path, audit)
            force_recorded_tree(status)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if all(state in {"gone", "reused"} for state in tree_states()):
                    return finish(3, "forced-owned: terminated recorded root tree after timeout")
                time.sleep(.1)
            return finish(2, "failed: forced-owned termination did not clear recorded tree")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return finish(2, f"refused/failed: {exc}")


def adopt_legacy_status(root: Path, actor: str, reason: str) -> int:
    directory = control_dir(root)
    token = uuid.uuid4().hex
    audit = {"requester": actor, "reason": reason, "token": token, "at": timestamp(),
             "operation": "adopt_legacy_status", "state_root": str(root)}
    audit_path = directory / "audit" / f"{token}.json"
    try:
        with file_lock(directory / "operator.lock"), file_lock(directory / "instance.lock"), file_lock(directory / "control.lock"):
            status_path = directory / "status.json"
            if not is_legacy_status(read_heartbeat(status_path)):
                raise ValueError("status is missing, invalid, or carries root identity; adoption refused")
            blockers = legacy_process_blockers(root)
            audit["process_blockers"] = blockers
            atomic_write_json(audit_path, audit)
            if blockers:
                raise ValueError(f"matching or unverifiable runtime processes: {blockers}")
            archive = directory / "legacy" / f"status.{timestamp().replace(':', '-')}.{token}.json"
            archive.parent.mkdir(parents=True, exist_ok=True)
            audit["archive"] = str(archive)
            atomic_write_json(audit_path, audit)  # durable intent before archive
            status_path.rename(archive)
            code, message = 0, f"legacy status archived: {archive}"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        code, message = 2, f"refused/failed: {exc}"
    audit.update(exit_code=code, outcome=message, finished_at=timestamp())
    atomic_write_json(audit_path, audit)
    print(message, flush=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root")
    parser.add_argument("--adopt-legacy-status", action="store_true")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--maintenance", choices=("on", "off"))
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout < 0:
        parser.error("--timeout must be finite and nonnegative")
    if bool(args.actor) != bool(args.reason) or (not args.maintenance and not args.actor):
        parser.error("a stop request requires --actor and --reason")
    if args.actor is not None and (not args.actor.strip() or not args.reason.strip()):
        parser.error("--actor and --reason must not be blank")
    if args.adopt_legacy_status and (not args.actor or args.maintenance):
        parser.error("--adopt-legacy-status requires --actor and --reason and cannot combine with --maintenance")
    try:
        root = resolve_state_root(REPO_ROOT, args.state_root)
        if args.adopt_legacy_status:
            return adopt_legacy_status(root, args.actor, args.reason)
        return stop(root, args.actor or "local-operator", args.reason or f"maintenance {args.maintenance}",
                    args.timeout, args.maintenance, request_stop=args.actor is not None)
    except (ValueError, OSError) as exc:
        print(f"refused/failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    from scripts._console import configure_console
    configure_console()
    raise SystemExit(main())
