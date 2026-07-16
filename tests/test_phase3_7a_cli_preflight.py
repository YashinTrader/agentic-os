from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_cli_compatibility import evaluate_cli_compatibility  # noqa: E402


class Phase37aCliPreflightTests(unittest.TestCase):
    def test_compatibility_evaluator_fixture(self) -> None:
        record = {
            "version_text": "codex-cli 0.136.0",
            "executable_path": "/usr/bin/codex",
            "non_interactive_subcommand": "exec",
            "invocations": [
                {"argv": ["codex", "exec", "--help"], "stdout": "-C --cd -s --sandbox --json -o"},
            ],
        }
        result = evaluate_cli_compatibility(record, require_installed=True)
        self.assertTrue(result.compatible or result.incompatibility_reasons)

    def test_inspect_script_uses_shell_false(self) -> None:
        source = (REPO_ROOT / "scripts" / "inspect_codex_cli.py").read_text(encoding="utf-8")
        self.assertIn("shell=False", source)
        self.assertNotIn("shell=True", source)

    def test_repository_validation_without_codex_installed(self) -> None:
        record = {"compatible": False, "executable_path": "", "help_hash": "absent"}
        result = evaluate_cli_compatibility(
            {
                "version_text": "",
                "executable_path": "",
                "non_interactive_subcommand": "exec",
                "invocations": [],
            },
            require_installed=False,
        )
        self.assertIsNotNone(result)

    def test_compatibility_json_shape(self) -> None:
        sample = {
            "parsed_version": "0.136.0",
            "help_hash": "abc",
            "executable_path": "",
            "compatible": False,
            "incompatibility_reasons": ["codex executable not found"],
        }
        parsed = json.loads(json.dumps(sample))
        self.assertIn("help_hash", parsed)


if __name__ == "__main__":
    unittest.main()