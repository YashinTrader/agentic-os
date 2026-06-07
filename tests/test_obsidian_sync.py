from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from integrations.obsidian.mapping import load_mapping, resolve_vault_path
from integrations.obsidian.sync_to_vault import collect_notes, run_sync, task_to_markdown
from integrations.obsidian.vault_writer import sanitize_filename, safe_join


class ObsidianSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        ignore = shutil.ignore_patterns(".codex", "__pycache__", "*.pyc")
        shutil.copytree(REPO_ROOT, self.root, ignore=ignore)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dry_run_writes_no_files(self) -> None:
        vault = self.root / "vault"
        vault.mkdir()
        report = run_sync(self.root, vault, dry_run=True)
        sync_root = vault / "AgenticOS"
        self.assertGreater(report.notes_planned, 0)
        self.assertEqual(report.notes_written, 0)
        self.assertFalse(sync_root.exists())

    def test_real_sync_writes_under_vault_root(self) -> None:
        vault = self.root / "vault"
        vault.mkdir()
        report = run_sync(self.root, vault, dry_run=False)
        sync_root = vault / "AgenticOS"
        self.assertGreater(report.notes_written, 0)
        self.assertTrue((sync_root / "00_Index.md").exists())
        for path in sync_root.rglob("*"):
            if path.is_file():
                self.assertTrue(str(path.resolve()).startswith(str(sync_root.resolve())))

    def test_existing_unrelated_vault_file_not_deleted(self) -> None:
        vault = self.root / "vault"
        vault.mkdir()
        personal = vault / "MyPersonalNote.md"
        personal.write_text("# Personal\n", encoding="utf-8")
        run_sync(self.root, vault, dry_run=False)
        self.assertTrue(personal.exists())
        self.assertEqual(personal.read_text(encoding="utf-8"), "# Personal\n")

    def test_path_traversal_blocked_in_safe_join(self) -> None:
        vault = self.root / "vault"
        vault.mkdir()
        with self.assertRaises(ValueError):
            safe_join(vault, "AgenticOS", "../outside.md")

    def test_resolve_vault_path_blocks_traversal(self) -> None:
        mapping = load_mapping(self.root)
        with self.assertRaises(ValueError):
            resolve_vault_path("../outside", mapping)

    def test_filename_sanitization(self) -> None:
        self.assertEqual(sanitize_filename('bad<>name'), "bad--name")
        self.assertEqual(sanitize_filename("  "), "untitled")

    def test_task_yaml_converts_to_markdown(self) -> None:
        task = {
            "id": "T-TEST",
            "title": "Test Task",
            "status": "active",
            "owner": "composer",
            "risk_level": "low",
            "objective": "Verify markdown conversion.",
            "acceptance": ["Tests pass"],
        }
        md = task_to_markdown(task, "active", "2026-06-07T18:00:00Z")
        self.assertIn("type: task", md)
        self.assertIn("T-TEST", md)
        self.assertIn("Verify markdown conversion", md)

    def test_logs_summary_handles_missing_log_gracefully(self) -> None:
        log_path = self.root / "logs" / "agent-events.jsonl"
        if log_path.exists():
            log_path.unlink()
        notes, warnings = collect_notes(self.root)
        self.assertTrue(any("Latest Events.md" in n.relative_path for n in notes))
        self.assertTrue(any(w for w in warnings))

    def test_logs_summary_handles_invalid_json_gracefully(self) -> None:
        log_path = self.root / "logs" / "agent-events.jsonl"
        log_path.write_text('{"ts":"2026-01-01T00:00:00Z","agent":"codex","task":"T-1","event":"started"}\nnot-json\n', encoding="utf-8")
        notes, warnings = collect_notes(self.root)
        self.assertTrue(any("invalid JSON" in w for w in warnings))
        self.assertTrue(any("Event Summary.md" in n.relative_path for n in notes))

    def test_registry_items_convert_to_notes(self) -> None:
        notes, _ = collect_notes(self.root)
        paths = {n.relative_path for n in notes}
        self.assertTrue(any(p.startswith("04_Skills/") and p.endswith(".md") for p in paths))
        self.assertTrue(any(p.startswith("05_MCPs/") and p.endswith(".md") for p in paths))
        self.assertTrue(any(p.startswith("03_Teams/") and p.endswith(".md") for p in paths))
        self.assertTrue(any(p.startswith("03_Roles/") and p.endswith(".md") for p in paths))

    def test_sync_cli_dry_run(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "sync_obsidian.py"), "--root", str(self.root), "--dry-run"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Notes planned", result.stdout)

    def test_sync_cli_json_output(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "sync_obsidian.py"),
                "--root",
                str(self.root),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        self.assertIn("notes_planned", data)
        self.assertTrue(data["dry_run"])

    def test_vault_root_folder_escape_rejected(self) -> None:
        mapping = load_mapping(self.root)
        mapping["vault_root_folder"] = ".."
        vault = self.root / "vault"
        vault.mkdir()
        with self.assertRaises(ValueError):
            run_sync(self.root, vault, dry_run=False, mapping=mapping)

    def test_output_folder_escape_rejected(self) -> None:
        mapping = load_mapping(self.root)
        mapping["output_folders"]["tasks_active"] = "../escape"
        with self.assertRaises(ValueError):
            collect_notes(self.root, mapping)

    def test_dashboard_loader_handles_missing_mapping(self) -> None:
        (self.root / "memory" / "obsidian_mapping.yaml").unlink()
        from dashboard.app import load_obsidian_mapping

        data, errors = load_obsidian_mapping(self.root)
        self.assertIsNone(data)
        self.assertTrue(any("does not exist" in e for e in errors))


if __name__ == "__main__":
    unittest.main()