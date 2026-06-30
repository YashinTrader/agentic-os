from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_cli_compatibility import (  # noqa: E402
    evaluate_cli_compatibility,
    normalize_compatibility_record,
)

FIXTURE_HELP = (REPO_ROOT / "tests" / "fixtures" / "codex_cli_exec_help.txt").read_text(encoding="utf-8")


def _fixture_discovery(*, version: str = "codex-cli 0.136.0", executable_path: str = "/usr/bin/codex") -> dict:
    return {
        "discovered_at": "2026-06-28T12:00:00Z",
        "executable_path": executable_path,
        "version_text": version,
        "non_interactive_subcommand": "exec",
        "invocations": [
            {
                "argv": ["codex", "exec", "--help"],
                "stdout": FIXTURE_HELP,
                "stderr": "",
                "exit_code": 0,
            }
        ],
    }


class CliCompatibilityTests(unittest.TestCase):
    def test_normalize_record_from_fixture(self) -> None:
        record = normalize_compatibility_record(_fixture_discovery())
        self.assertTrue(record["exec_subcommand_available"])
        self.assertEqual(record["output_flag"], "-o")
        self.assertEqual(record["prompt_mode"], "positional_trailing")
        self.assertTrue(record["help_hash"])

    def test_compatible_fixture(self) -> None:
        result = evaluate_cli_compatibility(_fixture_discovery(), require_installed=True)
        self.assertTrue(result.compatible)
        self.assertEqual(result.incompatibility_reasons, [])

    def test_missing_exec_subcommand_blocks(self) -> None:
        discovery = _fixture_discovery()
        discovery["invocations"][0]["stdout"] = "no exec here"
        result = evaluate_cli_compatibility(discovery, require_installed=True)
        self.assertFalse(result.compatible)
        self.assertTrue(any("exec" in r for r in result.incompatibility_reasons))

    def test_missing_output_flag_blocks(self) -> None:
        discovery = _fixture_discovery()
        discovery["invocations"][0]["stdout"] = "Usage: codex exec\nOptions:\n  -h, --help"
        result = evaluate_cli_compatibility(discovery, require_installed=True)
        self.assertFalse(result.compatible)

    def test_version_below_minimum_blocks(self) -> None:
        result = evaluate_cli_compatibility(
            _fixture_discovery(version="codex-cli 0.100.0"),
            require_installed=True,
        )
        self.assertFalse(result.compatible)
        self.assertTrue(any("minimum" in r for r in result.incompatibility_reasons))

    def test_not_installed_optional_mode(self) -> None:
        discovery = _fixture_discovery(executable_path="")
        result = evaluate_cli_compatibility(discovery, require_installed=False)
        self.assertTrue(result.compatible)


if __name__ == "__main__":
    unittest.main()