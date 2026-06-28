from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import validate as validate_mod  # noqa: E402


class Phase321HardeningTests(unittest.TestCase):
    def test_canonical_registry_requires_supports_execution(self) -> None:
        errors: list[str] = []
        warnings: list[str] = []
        validate_mod.validate_adapter_registry(errors)
        self.assertEqual(errors, [], msg=f"unexpected validator errors: {errors}; warnings={warnings}")

    def test_missing_supports_execution_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO_ROOT / "agents", root / "agents")
            registry_path = root / "agents" / "adapter_registry.yaml"
            data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
            data["adapters"][0].pop("supports_execution", None)
            registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

            original_root = validate_mod.ROOT
            try:
                validate_mod.ROOT = root
                errors: list[str] = []
                validate_mod.validate_adapter_registry(errors)
            finally:
                validate_mod.ROOT = original_root
            self.assertTrue(any("supports_execution" in e for e in errors))

    def test_string_true_supports_execution_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO_ROOT / "agents", root / "agents")
            registry_path = root / "agents" / "adapter_registry.yaml"
            data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
            data["adapters"][0]["supports_execution"] = "true"
            registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

            original_root = validate_mod.ROOT
            try:
                validate_mod.ROOT = root
                errors: list[str] = []
                validate_mod.validate_adapter_registry(errors)
            finally:
                validate_mod.ROOT = original_root
            self.assertTrue(any("must be a boolean" in e for e in errors))

    def test_only_dispatch_executor_imports_subprocess_for_runtime(self) -> None:
        runtime_modules = [
            REPO_ROOT / "dispatch" / "executor.py",
        ]
        for path in runtime_modules:
            source = path.read_text(encoding="utf-8")
            self.assertIn("subprocess", source)
        preview_source = (REPO_ROOT / "dispatch" / "preview.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", preview_source)

    def test_local_python_fixture_yaml_quoting_documented(self) -> None:
        registry = yaml.safe_load((REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8"))
        fixture = next(a for a in registry["adapters"] if a["id"] == "local-python-exec-test")
        self.assertIn("Quoted command_template", fixture.get("notes", ""))
        self.assertIn("python -c", fixture["command_template"])


if __name__ == "__main__":
    unittest.main()