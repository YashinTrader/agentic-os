from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.agent_context_bundle import (  # noqa: E402
    build_context_bundle,
    bundle_root,
    compute_bundle_hash,
)


class CodexContextBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.root,
            ignore=shutil.ignore_patterns("runtime", ".git", "__pycache__"),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_context_bundle_atomic_files(self) -> None:
        task = {"id": "T-CTX", "objective": "test objective", "acceptance": ["done"]}
        preview = {"run_id": "dispatch-ctx-1", "timeout_seconds": 600}
        policy = {"approval_level": "human", "timeout_seconds": 600}
        manifest = build_context_bundle(
            self.root,
            run_id="dispatch-ctx-1",
            task=task,
            plan={"task_id": "T-CTX"},
            preview=preview,
            adapter_policy=policy,
            worktree_path=str(self.root / "wt"),
            base_sha="deadbeef",
            allowed_paths=["src/"],
            forbidden_operations=["push", "merge"],
            verification_commands=["python scripts/validate.py"],
        )
        bundle = bundle_root(self.root, "dispatch-ctx-1")
        self.assertTrue((bundle / "task.yaml").exists())
        self.assertTrue((bundle / "instructions.md").exists())
        self.assertTrue((bundle / "manifest.json").exists())
        self.assertEqual(manifest["bundle_hash"], compute_bundle_hash(bundle))

    def test_manifest_excludes_secrets(self) -> None:
        task = {"id": "T-SEC", "objective": "x"}
        build_context_bundle(
            self.root,
            run_id="dispatch-sec-1",
            task=task,
            plan={},
            preview={"timeout_seconds": 30},
            adapter_policy={"approval_level": "human"},
            worktree_path="/wt",
            base_sha="abc",
            allowed_paths=["."],
            forbidden_operations=[],
            verification_commands=[],
        )
        manifest = json.loads(
            (bundle_root(self.root, "dispatch-sec-1") / "manifest.json").read_text(encoding="utf-8")
        )
        blob = json.dumps(manifest)
        self.assertNotIn("AGENTIC_OS_HUMAN_APPROVAL_KEY", blob)
        self.assertNotIn("OPENAI_API_KEY", blob)


if __name__ == "__main__":
    unittest.main()