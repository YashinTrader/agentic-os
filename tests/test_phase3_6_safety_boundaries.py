from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import build_draft_activation_manifest  # noqa: E402
from dispatch.codex_canary_gates import evaluate_canary_execution_gates  # noqa: E402
from dispatch.execution_gate import adapter_supports_execution  # noqa: E402

PHASE_3_6_MODULES = (
    "dispatch/codex_adapter.py",
    "dispatch/codex_activation.py",
    "dispatch/codex_canary_contract.py",
    "dispatch/codex_cli_compatibility.py",
    "dispatch/codex_canary_gates.py",
    "scripts/inspect_codex_cli.py",
    "scripts/validate_codex_activation.py",
    "scripts/prepare_codex_canary.py",
    "scripts/run_codex_canary.py",
)


class Phase36SafetyBoundaryTests(unittest.TestCase):
    def test_execution_capable_adapters_include_canary_candidate(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        capable = [a["id"] for a in registry["adapters"] if adapter_supports_execution(a)]
        self.assertEqual(sorted(capable), ["codex-restricted", "local-python-exec-test"])

    def test_codex_restricted_activation_candidate_gated(self) -> None:
        entry = next(
            a for a in yaml.safe_load(
                (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
            )["adapters"]
            if a["id"] == "codex-restricted"
        )
        self.assertTrue(entry["supports_execution"])
        self.assertEqual(entry.get("execution_scope"), "canary_only")
        self.assertFalse(entry.get("live_run_authorized", True))

    def test_phase36_modules_no_shell_true(self) -> None:
        for rel in PHASE_3_6_MODULES:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), rel)
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", source, rel)

    def test_codex_adapter_no_subprocess(self) -> None:
        source = (REPO_ROOT / "dispatch" / "codex_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run", source)

    def test_canary_runner_refuses_ordinary_invocation(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "run_codex_canary.py")],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("refused", completed.stdout.lower())

    def test_execute_alone_refuses(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_codex_canary.py"),
                "--execute-canary",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)

    def test_fake_manifest_alone_refuses(self) -> None:
        manifest = build_draft_activation_manifest(
            REPO_ROOT,
            activation_id="activation-fake",
            reviewed_commit_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            base_sha="2af82a9e7e812e05059b69653583d1c78dfa43b1",
            cli_version="0.136.0",
            cli_help_hash="fake",
        )
        tmp = REPO_ROOT / "runtime" / "dispatch" / "codex_activation" / "activation-fake-test.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(manifest), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_codex_canary.py"),
                "--manifest",
                str(tmp),
                "--execute-canary",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)

    def test_gates_never_invoke_codex_subprocess(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        adapter = next(a for a in registry["adapters"] if a["id"] == "codex-restricted")
        with mock.patch("subprocess.run") as run_mock:
            evaluate_canary_execution_gates(
                REPO_ROOT,
                registry_adapter=adapter,
                execute_flag=True,
            )
            run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()