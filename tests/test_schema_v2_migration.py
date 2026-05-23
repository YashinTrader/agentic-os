from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SchemaV2MigrationTests(unittest.TestCase):
    def make_repo(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for name in ("scripts", "tasks", "logs", "handoffs", "decisions", "docs"):
            src = ROOT / name
            dst = tmp / name
            if src.is_dir():
                shutil.copytree(src, dst)
        return tmp

    def run_script(self, root: Path, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(root / "scripts" / script)],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_migration_renames_v1_fields(self) -> None:
        root = self.make_repo()
        try:
            path = root / "tasks" / "active" / "T-9001.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "T-9001",
                        "title": "v1 task",
                        "owner": "codex",
                        "status": "todo",
                        "created": "2026-05-23T00:00:00Z",
                        "updated": "2026-05-23T00:00:00Z",
                        "objective": "Migrate me.",
                        "inputs": ["README.md"],
                        "outputs": ["tasks/active/T-9001.yaml"],
                        "constraints": ["None."],
                        "acceptance_criteria": ["Renamed."],
                        "handoff_notes": "Notes.",
                        "risk_level": "low",
                        "requires_human_approval": False,
                        "priority": "P2",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            result = self.run_script(root, "migrate_schema_v2.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            migrated = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertNotIn("created", migrated)
            self.assertNotIn("acceptance_criteria", migrated)
            self.assertEqual(migrated["created_at"], "2026-05-23T00:00:00Z")
            self.assertEqual(migrated["acceptance"], ["Renamed."])
            self.assertEqual(migrated["notes"], "Notes.")
            self.assertEqual(migrated["status"], "ready")
            self.assertEqual(migrated["priority"], "medium")
        finally:
            shutil.rmtree(root)

    def test_migration_is_idempotent(self) -> None:
        root = self.make_repo()
        try:
            first = self.run_script(root, "migrate_schema_v2.py")
            self.assertEqual(first.returncode, 0, first.stderr)
            snapshots = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in (root / "tasks").rglob("*.yaml")}
            second = self.run_script(root, "migrate_schema_v2.py")
            self.assertEqual(second.returncode, 0, second.stderr)
            after = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in (root / "tasks").rglob("*.yaml")}
            self.assertEqual(snapshots, after)
        finally:
            shutil.rmtree(root)

    def test_validate_rejects_mixed_rename_pair(self) -> None:
        root = self.make_repo()
        try:
            path = root / "tasks" / "active" / "T-9002.yaml"
            data = {
                "id": "T-9002",
                "title": "mixed task",
                "owner": "codex",
                "reviewer": "claude",
                "created_by": "codex",
                "status": "ready",
                "phase": "1.5",
                "created": "2026-05-23T00:00:00Z",
                "created_at": "2026-05-23T00:00:00Z",
                "updated_at": "2026-05-23T00:00:00Z",
                "objective": "Reject mixed fields.",
                "context": "Reject mixed fields.",
                "goals": ["Reject mixed fields."],
                "non_goals": [],
                "inputs": ["README.md"],
                "outputs": ["tasks/active/T-9002.yaml"],
                "constraints": ["None."],
                "acceptance": ["Rejected."],
                "human_approval_checklist": [],
                "notes": "None.",
                "risk_level": "low",
                "requires_human_approval": False,
                "priority": "medium",
            }
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            result = self.run_script(root, "validate.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("contains both 'created' and 'created_at'", result.stdout)
        finally:
            shutil.rmtree(root)

    def test_validate_requires_reviewer_for_review_or_done(self) -> None:
        root = self.make_repo()
        try:
            result = self.run_script(root, "migrate_schema_v2.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            path = root / "tasks" / "active" / "EXAMPLE.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["status"] = "review"
            data.pop("reviewer", None)
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            result = self.run_script(root, "validate.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewer is required", result.stdout)
        finally:
            shutil.rmtree(root)

    def test_validate_requires_checklist_when_human_approval_required(self) -> None:
        root = self.make_repo()
        try:
            result = self.run_script(root, "migrate_schema_v2.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            path = root / "tasks" / "active" / "EXAMPLE.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["requires_human_approval"] = True
            data["human_approval_checklist"] = []
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            result = self.run_script(root, "validate.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("human_approval_checklist is empty", result.stdout)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
