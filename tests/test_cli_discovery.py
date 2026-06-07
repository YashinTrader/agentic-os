from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from daemon.cli_discovery import CLI_SPECS, discover_clis, discover_one
from daemon.registry_writer import inventory_path, status_path, write_daemon_status, write_inventory


REQUIRED_TOOL_FIELDS = {
    "id",
    "display_name",
    "available",
    "path",
    "version",
    "version_command_used",
    "detection_method",
    "last_checked",
    "notes",
}


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CliDiscoveryTests(unittest.TestCase):
    def test_tracked_cli_count_is_fourteen(self) -> None:
        self.assertEqual(len(CLI_SPECS), 14)

    def test_missing_cli_does_not_crash(self) -> None:
        def fake_which(_name: str) -> None:
            return None

        inventory = discover_clis(which_func=fake_which)
        self.assertEqual(inventory["summary"]["total"], len(CLI_SPECS))
        self.assertEqual(inventory["summary"]["available"], 0)
        self.assertEqual(inventory["summary"]["missing"], len(CLI_SPECS))
        for tool in inventory["tools"]:
            self.assertFalse(tool["available"])
            self.assertIsNone(tool["path"])
            self.assertIn("not found", (tool["notes"] or "").lower())

    def test_discovery_result_has_required_fields(self) -> None:
        inventory = discover_clis(
            which_func=lambda name: "/fake/bin/git" if name == "git" else None,
            run_func=lambda _cmd, _timeout: FakeCompletedProcess(stdout="git version 2.43.0"),
            checked_at="2026-06-07T12:00:00Z",
        )
        self.assertIn("schema_version", inventory)
        self.assertIn("generated_at", inventory)
        self.assertIn("summary", inventory)
        self.assertIn("tools", inventory)
        for tool in inventory["tools"]:
            self.assertEqual(REQUIRED_TOOL_FIELDS, set(tool.keys()))

    def test_version_command_timeout_is_handled_safely(self) -> None:
        def slow_run(_command: list[str], _timeout: float) -> None:
            return None

        entry = discover_one(
            CLI_SPECS[0],
            which_func=lambda _name: "/usr/bin/git",
            run_func=slow_run,
            checked_at="2026-06-07T12:00:00Z",
        )
        self.assertTrue(entry["available"])
        self.assertIsNone(entry["version"])
        self.assertIsNotNone(entry["notes"])

    def test_version_command_failure_is_handled_safely(self) -> None:
        entry = discover_one(
            CLI_SPECS[0],
            which_func=lambda _name: "/usr/bin/git",
            run_func=lambda _cmd, _timeout: FakeCompletedProcess(returncode=1, stderr="failed"),
            checked_at="2026-06-07T12:00:00Z",
        )
        self.assertTrue(entry["available"])
        self.assertIsNone(entry["version"])
        self.assertIsNotNone(entry["notes"])

    def test_inventory_writer_creates_expected_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = {
                "schema_version": "1.0",
                "generated_at": "2026-06-07T12:00:00Z",
                "summary": {"total": 1, "available": 1, "missing": 0},
                "tools": [
                    {
                        "id": "git",
                        "display_name": "Git",
                        "available": True,
                        "path": "/usr/bin/git",
                        "version": "2.43.0",
                        "version_command_used": "git --version",
                        "detection_method": "shutil.which",
                        "last_checked": "2026-06-07T12:00:00Z",
                        "notes": None,
                    }
                ],
            }
            path = write_inventory(root, inventory)
            self.assertTrue(path.exists())
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["available"], 1)
            self.assertEqual(loaded["tools"][0]["id"], "git")

    def test_daemon_once_writes_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir(parents=True)
            (root / "logs" / "agent-events.jsonl").write_text(
                '{"ts":"2026-06-07T12:00:00Z","agent":"codex","type":"note","detail":"seed"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "-m", "daemon.daemon", "--root", str(root), "--once"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

            inv = inventory_path(root)
            status = status_path(root)
            self.assertTrue(inv.exists())
            self.assertTrue(status.exists())

            status_data = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(status_data["mode"], "once")
            self.assertIn("summary", status_data)
            self.assertEqual(status_data["status"], "ok")

    def test_dashboard_loads_inventory_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_dir = root / "runtime" / "registry"
            status_dir = root / "runtime" / "status"
            registry_dir.mkdir(parents=True)
            status_dir.mkdir(parents=True)

            inventory = {
                "schema_version": "1.0",
                "generated_at": "2026-06-07T12:00:00Z",
                "summary": {"total": 1, "available": 1, "missing": 0},
                "tools": [
                    {
                        "id": "git",
                        "display_name": "Git",
                        "available": True,
                        "path": "/usr/bin/git",
                        "version": "2.43.0",
                        "version_command_used": "git --version",
                        "detection_method": "shutil.which",
                        "last_checked": "2026-06-07T12:00:00Z",
                        "notes": None,
                    }
                ],
            }
            write_inventory(root, inventory)
            write_daemon_status(root, mode="once", inventory=inventory)

            from dashboard.app import load_cli_inventory, load_daemon_status

            loaded_inventory, inv_errors = load_cli_inventory(root)
            loaded_status, status_errors = load_daemon_status(root)
            self.assertEqual(inv_errors, [])
            self.assertEqual(status_errors, [])
            self.assertIsNotNone(loaded_inventory)
            self.assertIsNotNone(loaded_status)
            self.assertEqual(loaded_inventory["tools"][0]["id"], "git")


class DaemonStatusWriterTests(unittest.TestCase):
    def test_write_daemon_status_records_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = {
                "generated_at": "2026-06-07T12:00:00Z",
                "summary": {"total": 0, "available": 0, "missing": 0},
            }
            path = write_daemon_status(root, mode="once", inventory=inventory, errors=["boom"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["errors"], ["boom"])


if __name__ == "__main__":
    unittest.main()