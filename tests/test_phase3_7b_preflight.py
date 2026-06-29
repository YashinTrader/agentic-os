"""Phase 3.7B Codex canary preflight — package preparation; no live execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_activation import (  # noqa: E402
    activation_bundle_dir,
    validate_activation_manifest_v2,
)
from dispatch.codex_activation_gate import (  # noqa: E402
    PHASE3_7B_BLOCKED_REASON,
    disabled_path,
    evaluate_activation_gates,
    evaluate_phase3_7b_authorization,
    evaluate_post_canary_suspension,
    phase3_7b_authorization_path,
)
from dispatch.codex_canary_contract import expected_canary_relative_path  # noqa: E402
from dispatch.codex_preflight_37b import (  # noqa: E402
    AUTHORIZATION_LIVE_FILENAME,
    AUTHORIZATION_TEMPLATE_FILENAME,
    PHASE37B_DEFAULT_ACTIVATION_ID,
    PHASE37B_MANIFEST_STATUS,
    PHASE37B_REQUEST_STATUS,
    PHASE37B_TASK_ID,
    PHASE37B_TEMPLATE_STATUS,
    build_authorization_template,
    build_canary_contract_record,
    build_canary_markdown_content,
    build_context_bundle_for_preflight,
    build_live_command_preview,
    build_phase37b_human_request,
    build_phase37b_manifest,
    build_phase37b_preview,
    evaluate_preflight_gates,
    new_immutable_run_id,
    validate_preflight_package,
)
from dispatch.execution_route_policy import (  # noqa: E402
    DEDICATED_CANARY_RUNNER_REASON,
    ROUTE_CODEX_CANARY,
    ROUTE_GENERIC_DISPATCH,
    evaluate_execution_route,
)
from dispatch.executor import execute_dispatch  # noqa: E402

REVIEWED_SHA = "2fa6424675899cb3d89a6f7f266086751fdf5975"
CLI_VERSION = "0.136.0"
CLI_HELP_HASH = "9f86f0115238ddde2514587e5f95b0ab0aa6b89495e5912878d49ad26038aa19"


def _cli_compat_fixture() -> dict:
    return {
        "compatible": True,
        "executable_path": "C:/bin/codex",
        "version_raw": f"codex-cli {CLI_VERSION}",
        "parsed_version": CLI_VERSION,
        "help_hash": CLI_HELP_HASH,
        "exec_subcommand_available": True,
        "output_flag": "-o",
        "invocations": [
            {
                "argv": ["codex", "exec", "--help"],
                "stdout": "Usage: codex exec -C -s --json -o, --output-last-message <FILE>",
            }
        ],
    }


def _allocation_fixture(root: Path, run_id: str) -> dict:
    wt = root / "runtime" / "worktrees" / f"wt-{run_id}"
    wt.mkdir(parents=True, exist_ok=True)
    return {
        "allocation_id": f"alloc-{run_id}",
        "task_id": PHASE37B_TASK_ID,
        "run_id": run_id,
        "worktree_path": str(wt),
        "branch_name": f"agent/codex/{PHASE37B_TASK_ID}/{run_id}",
        "base_sha": REVIEWED_SHA,
        "status": "allocated",
    }


class Phase37bPreflightFixtureMixin:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.root,
            ignore=shutil.ignore_patterns(
                ".git",
                "__pycache__",
                "*.pyc",
                "runtime/dispatch/runs/*",
                "runtime/dispatch/codex_activation/*",
            ),
        )
        self.run_id = new_immutable_run_id()
        self.activation_id = f"activation-37b-test-{self.run_id[-8:]}"
        self.allocation = _allocation_fixture(self.root, self.run_id)
        self.expected_file = expected_canary_relative_path(self.run_id)
        self.cli_compat = _cli_compat_fixture()
        compat_path = self.root / "runtime" / "registry" / "codex_cli_compatibility.json"
        compat_path.parent.mkdir(parents=True, exist_ok=True)
        compat_path.write_text(json.dumps(self.cli_compat, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _registry_adapter(self) -> dict:
        registry = yaml.safe_load(
            (self.root / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        return next(a for a in registry["adapters"] if a["id"] == "codex-restricted")

    def _build_package(self) -> dict:
        from dispatch.codex_adapter import load_codex_restricted_adapter

        dedicated = load_codex_restricted_adapter(self.root)
        preview_pending: dict = {"status": "preview_pending_allocation"}
        ctx = build_context_bundle_for_preflight(
            self.root,
            run_id=self.run_id,
            worktree_path=str(self.allocation["worktree_path"]),
            base_sha=REVIEWED_SHA,
            expected_file=self.expected_file,
            preview=preview_pending,
        )
        context_hash = str(ctx["bundle_hash"])
        canary_contract = build_canary_contract_record(
            run_id=self.run_id,
            reviewed_commit_sha=REVIEWED_SHA,
            cli_version=CLI_VERSION,
            context_bundle_hash=context_hash,
            expected_relative_path=self.expected_file,
        )
        preview = build_phase37b_preview(
            self.root,
            run_id=self.run_id,
            task_id=PHASE37B_TASK_ID,
            allocation_record=self.allocation,
            cli_compatibility=self.cli_compat,
            canary_contract=canary_contract,
            context_bundle_hash=context_hash,
        )
        manifest = build_phase37b_manifest(
            self.root,
            activation_id=self.activation_id,
            reviewed_commit_sha=REVIEWED_SHA,
            cli_version=CLI_VERSION,
            cli_help_hash=CLI_HELP_HASH,
            context_bundle_hash=context_hash,
            worktree_allocation_id=str(self.allocation["allocation_id"]),
        )
        manifest["canary_contract_hash"] = str(canary_contract["contract_hash"])
        human_request = build_phase37b_human_request(
            self.root,
            activation_id=self.activation_id,
            reviewed_commit_sha=REVIEWED_SHA,
            cli_version=CLI_VERSION,
            context_bundle_hash=context_hash,
            worktree_path=str(self.allocation["worktree_path"]),
            expected_file=self.expected_file,
            run_id=self.run_id,
        )
        auth_template = build_authorization_template(
            activation_id=self.activation_id,
            task_id=PHASE37B_TASK_ID,
            run_id=self.run_id,
            reviewed_commit_sha=REVIEWED_SHA,
            canary_contract_hash=str(canary_contract["contract_hash"]),
            context_bundle_hash=context_hash,
            preview_hash=str(preview["preview_hash"]),
            worktree_allocation_id=str(self.allocation["allocation_id"]),
            expected_file=self.expected_file,
        )
        bundle = activation_bundle_dir(self.root, self.activation_id)
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "activation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (bundle / "human_approval_request.json").write_text(json.dumps(human_request, indent=2), encoding="utf-8")
        (bundle / AUTHORIZATION_TEMPLATE_FILENAME).write_text(json.dumps(auth_template, indent=2), encoding="utf-8")
        (bundle / "canary_contract.json").write_text(json.dumps(canary_contract, indent=2), encoding="utf-8")
        (bundle / "execution_preview.json").write_text(json.dumps(preview, indent=2), encoding="utf-8")
        (bundle / "worktree_allocation.json").write_text(json.dumps(self.allocation, indent=2), encoding="utf-8")
        (bundle / "preflight.json").write_text(
            json.dumps(
                {
                    "codex_subprocess_invoked": False,
                    "approval_consumed": False,
                    "dry_run_blocked": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "manifest": manifest,
            "human_request": human_request,
            "auth_template": auth_template,
            "canary_contract": canary_contract,
            "preview": preview,
            "context_hash": context_hash,
        }


class Phase37bPackageConsistencyTests(Phase37bPreflightFixtureMixin, unittest.TestCase):
    def test_preflight_package_consistency(self) -> None:
        pkg = self._build_package()
        blockers = validate_preflight_package(self.root, self.activation_id, reviewed_sha=REVIEWED_SHA)
        self.assertEqual(blockers, [])
        self.assertEqual(pkg["manifest"]["status"], PHASE37B_MANIFEST_STATUS)
        self.assertEqual(pkg["human_request"]["status"], PHASE37B_REQUEST_STATUS)
        self.assertEqual(pkg["auth_template"]["status"], PHASE37B_TEMPLATE_STATUS)

    def test_worktree_allocation_binding(self) -> None:
        pkg = self._build_package()
        self.assertEqual(pkg["manifest"]["worktree_allocation_id"], self.allocation["allocation_id"])
        alloc_path = activation_bundle_dir(self.root, self.activation_id) / "worktree_allocation.json"
        alloc = json.loads(alloc_path.read_text(encoding="utf-8"))
        self.assertEqual(alloc["task_id"], PHASE37B_TASK_ID)
        self.assertEqual(alloc["run_id"], self.run_id)
        self.assertEqual(alloc["base_sha"], REVIEWED_SHA)

    def test_cli_compatibility_binding(self) -> None:
        pkg = self._build_package()
        self.assertEqual(pkg["manifest"]["cli_version"], CLI_VERSION)
        self.assertEqual(pkg["manifest"]["cli_help_hash"], CLI_HELP_HASH)
        self.assertEqual(pkg["preview"]["codex_version"], CLI_VERSION)

    def test_context_and_canary_hashes(self) -> None:
        pkg = self._build_package()
        self.assertTrue(pkg["context_hash"])
        self.assertTrue(pkg["canary_contract"]["contract_hash"])
        self.assertEqual(
            pkg["manifest"]["context_bundle_hash"],
            pkg["context_hash"],
        )

    def test_exact_expected_file(self) -> None:
        pkg = self._build_package()
        self.assertEqual(pkg["canary_contract"]["expected_relative_path"], self.expected_file)
        self.assertTrue(self.expected_file.startswith("docs/codex-canary-"))
        self.assertEqual(pkg["human_request"]["expected_file"], self.expected_file)

    def test_canary_markdown_content_shape(self) -> None:
        content = build_canary_markdown_content(run_id=self.run_id)
        self.assertIn("# Codex Canary", content)
        self.assertIn(f"Run ID: {self.run_id}", content)
        self.assertIn("Maximum runs:", content)
        self.assertIn("1", content.split("Maximum runs:")[1])
        self.assertIn("10 minutes", content)

    def test_one_run_maximum(self) -> None:
        pkg = self._build_package()
        self.assertEqual(pkg["manifest"]["maximum_runs"], 1)
        self.assertEqual(pkg["manifest"]["runs_consumed"], 0)
        self.assertEqual(pkg["human_request"]["maximum_runs"], 1)

    def test_awaiting_human_states(self) -> None:
        pkg = self._build_package()
        self.assertEqual(pkg["manifest"]["status"], "awaiting_human_approval")
        self.assertEqual(pkg["human_request"]["status"], "awaiting_human_decision")
        self.assertIn("does not authorize", pkg["human_request"]["statement"].lower())

    def test_authorization_template_not_live(self) -> None:
        self._build_package()
        live = phase3_7b_authorization_path(self.root, self.activation_id)
        self.assertFalse(live.exists())
        ok, reason = evaluate_phase3_7b_authorization(self.root, self.activation_id)
        self.assertFalse(ok)
        self.assertEqual(reason, PHASE3_7B_BLOCKED_REASON)

    def test_template_not_accepted_as_authorization(self) -> None:
        self._build_package()
        template = activation_bundle_dir(self.root, self.activation_id) / AUTHORIZATION_TEMPLATE_FILENAME
        shutil.copy(template, phase3_7b_authorization_path(self.root, self.activation_id))
        ok, _ = evaluate_phase3_7b_authorization(self.root, self.activation_id)
        self.assertFalse(ok)

    def test_no_approval_signature_in_request(self) -> None:
        pkg = self._build_package()
        for forbidden in ("signature", "approved", "approval_hmac"):
            self.assertNotIn(forbidden, pkg["human_request"])

    def test_manifest_phase37b_validation(self) -> None:
        pkg = self._build_package()
        result = validate_activation_manifest_v2(
            pkg["manifest"],
            repo_root=self.root,
            current_reviewed_sha=REVIEWED_SHA,
            cli_help_hash=CLI_HELP_HASH,
            phase="3.7B",
        )
        self.assertTrue(result.ready_for_review, msg=result.blockers)


class Phase37bGateAndRouteTests(Phase37bPreflightFixtureMixin, unittest.TestCase):
    def test_dry_run_blocked(self) -> None:
        from dispatch.codex_adapter import load_codex_restricted_adapter

        pkg = self._build_package()
        report = evaluate_preflight_gates(
            self.root,
            registry_adapter=self._registry_adapter(),
            dedicated_adapter=load_codex_restricted_adapter(self.root),
            activation_manifest=pkg["manifest"],
            cli_compatibility=self.cli_compat,
            allocation_record=self.allocation,
            human_request=pkg["human_request"],
        )
        self.assertTrue(report.blocked)
        self.assertFalse(report.codex_subprocess_invoked)
        self.assertFalse(report.approval_consumed)
        joined = " ".join(report.blocked_reasons)
        self.assertIn(PHASE3_7B_BLOCKED_REASON, joined)

    def test_generic_executor_refuses(self) -> None:
        adapter = self._registry_adapter()
        route = evaluate_execution_route(adapter, ROUTE_GENERIC_DISPATCH)
        self.assertFalse(route.allowed)
        self.assertIn(DEDICATED_CANARY_RUNNER_REASON, route.reasons)

    def test_dedicated_runner_refuses_without_authorization(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_codex_canary.py"),
                "--execute-canary",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(completed.returncode, 3)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "refused")
        self.assertFalse(report["codex_subprocess_invoked"])
        self.assertFalse(report["approval_consumed"])

    def test_no_subprocess_in_preflight_gates(self) -> None:
        from dispatch.codex_adapter import load_codex_restricted_adapter

        pkg = self._build_package()
        with mock.patch("subprocess.run") as run_mock:
            report = evaluate_preflight_gates(
                self.root,
                registry_adapter=self._registry_adapter(),
                dedicated_adapter=load_codex_restricted_adapter(self.root),
                activation_manifest=pkg["manifest"],
                cli_compatibility=self.cli_compat,
                allocation_record=self.allocation,
                human_request=pkg["human_request"],
            )
            run_mock.assert_not_called()
        self.assertFalse(report.approval_consumed)

    def test_emergency_disable_blocks(self) -> None:
        from dispatch.codex_adapter import load_codex_restricted_adapter

        pkg = self._build_package()
        disable = disabled_path(self.root, self.activation_id)
        disable.parent.mkdir(parents=True, exist_ok=True)
        disable.write_text(
            json.dumps({"disabled": True, "reason": "test fixture"}),
            encoding="utf-8",
        )
        try:
            gate = evaluate_activation_gates(
                self.root,
                registry_adapter=self._registry_adapter(),
                dedicated_adapter=load_codex_restricted_adapter(self.root),
                activation_manifest=pkg["manifest"],
                cli_compatibility=self.cli_compat,
                allocation_record=self.allocation,
                execute_flag=True,
                activation_id=self.activation_id,
            )
            self.assertFalse(gate.allowed)
            self.assertTrue(any("emergency disable" in r for r in gate.blocked_reasons))
        finally:
            disable.unlink(missing_ok=True)

    def test_post_attempt_suspension_contract(self) -> None:
        state = evaluate_post_canary_suspension(
            runs_consumed=1,
            maximum_runs=1,
            attempt_status="completed",
        )
        self.assertTrue(state["activation_exhausted"])
        self.assertTrue(state["second_attempt_blocked"])
        self.assertFalse(state["automatic_retry_allowed"])
        self.assertEqual(state["status_after_attempt"], "suspended_pending_review")


class Phase37bPreviewAndCommandTests(unittest.TestCase):
    def test_live_command_preview_no_secrets(self) -> None:
        preview = build_live_command_preview(
            activation_id=PHASE37B_DEFAULT_ACTIVATION_ID,
            run_id="canary-test-run",
            allocation_id="alloc-test",
            approval_placeholder="runtime/approvals/<signed>.json",
            authorization_placeholder="runtime/dispatch/codex_activation/x/phase3_7b_authorization.json",
        )
        blob = json.dumps(preview)
        for forbidden in ("AGENTIC_OS_HUMAN_APPROVAL_KEY", "signature", "hmac", "token", "password"):
            self.assertNotIn(forbidden, blob.lower())
        self.assertIn("--execute-canary", preview["canary_runner"])
        self.assertIn("disable_codex_canary.py", preview["emergency_disable"])

    def test_inspect_script_resolves_executable_path(self) -> None:
        source = (REPO_ROOT / "scripts" / "inspect_codex_cli.py").read_text(encoding="utf-8")
        self.assertIn("shutil.which", source)
        self.assertIn("invocation_executable", source)

    def test_prepare_script_no_prompt_exec(self) -> None:
        source = (REPO_ROOT / "scripts" / "prepare_codex_canary_37b.py").read_text(encoding="utf-8")
        self.assertNotIn('["codex", "exec"', source)
        self.assertIn("inspect_codex_cli", source)

    def test_repository_cli_compatibility_when_present(self) -> None:
        compat_path = REPO_ROOT / "runtime" / "registry" / "codex_cli_compatibility.json"
        if not compat_path.is_file():
            self.skipTest("codex_cli_compatibility.json not generated in this environment")
        record = json.loads(compat_path.read_text(encoding="utf-8"))
        if record.get("executable_path"):
            self.assertTrue(record.get("parsed_version") or record.get("version_raw"))
            self.assertTrue(record.get("help_hash"))


class Phase37bRepositorySafetyTests(unittest.TestCase):
    def test_no_live_authorization_in_repo(self) -> None:
        activation_root = REPO_ROOT / "runtime" / "dispatch" / "codex_activation"
        if not activation_root.is_dir():
            return
        for bundle in activation_root.iterdir():
            live = bundle / AUTHORIZATION_LIVE_FILENAME
            if live.exists():
                data = json.loads(live.read_text(encoding="utf-8"))
                self.assertNotEqual(data.get("status"), "authorized")

    def test_no_committed_canary_result_files(self) -> None:
        for path in REPO_ROOT.glob("docs/codex-canary-*.md"):
            self.fail(f"live canary file must not be committed: {path}")

    def test_dedicated_route_allowed_at_policy(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        codex = next(a for a in registry["adapters"] if a["id"] == "codex-restricted")
        decision = evaluate_execution_route(codex, ROUTE_CODEX_CANARY)
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()