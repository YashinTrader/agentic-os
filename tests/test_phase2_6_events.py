from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from daemon.registry_writer import append_discovery_event  # noqa: E402
from integrations.obsidian.sync_to_vault import run_sync  # noqa: E402
from protocol.emit_event import append_event  # noqa: E402
from protocol.event_types import ALLOWED_EVENT_TYPES  # noqa: E402


class Phase26EventEmitterTests(unittest.TestCase):
    def test_daemon_emits_discovery_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            inventory = {
                "generated_at": "2026-06-07T12:00:00Z",
                "summary": {"total": 2, "available": 1, "missing": 1},
            }
            append_discovery_event(root, inventory, mode="once")
            line = (root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").strip()
            event = json.loads(line)
            self.assertEqual(event["type"], "discovery_completed")
            self.assertEqual(event["agent"], "daemon")

    def test_daemon_emits_error_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            inventory = {"generated_at": "2026-06-07T12:00:00Z", "summary": {"total": 0, "available": 0, "missing": 0}}
            append_discovery_event(root, inventory, mode="once", errors=["discovery failed"])
            line = (root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").strip()
            event = json.loads(line)
            self.assertEqual(event["type"], "error")

    def test_obsidian_dry_run_emits_vault_sync_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
            shutil.copytree(REPO_ROOT, root, ignore=ignore)
            (root / "logs" / "agent-events.jsonl").write_text(
                '{"ts":"2026-06-07T12:00:00Z","agent":"codex","type":"note","detail":"seed"}\n',
                encoding="utf-8",
            )
            vault = root / "vault"
            vault.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "sync_obsidian.py"),
                    "--root",
                    str(root),
                    "--vault",
                    str(vault),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = (root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()
            types = [json.loads(line)["type"] for line in lines if line.strip()]
            self.assertIn("vault_sync_planned", types)

    def test_obsidian_real_sync_emits_vault_sync_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
            shutil.copytree(REPO_ROOT, root, ignore=ignore)
            (root / "logs" / "agent-events.jsonl").write_text(
                '{"ts":"2026-06-07T12:00:00Z","agent":"codex","type":"note","detail":"seed"}\n',
                encoding="utf-8",
            )
            vault = root / "vault"
            vault.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "sync_obsidian.py"),
                    "--root",
                    str(root),
                    "--vault",
                    str(vault),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = (root / "logs" / "agent-events.jsonl").read_text(encoding="utf-8").splitlines()
            types = [json.loads(line)["type"] for line in lines if line.strip()]
            self.assertIn("vault_sync_completed", types)

    def test_orchestration_planned_is_canonical(self) -> None:
        self.assertIn("orchestration_planned", ALLOWED_EVENT_TYPES)

    def test_emit_event_rejects_unknown_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                append_event(root, agent="test", event_type="not_a_real_event")


if __name__ == "__main__":
    unittest.main()