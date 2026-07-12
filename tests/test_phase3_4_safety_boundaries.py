from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dashboard.safety_scan import (  # noqa: E402
    find_submit_controls,
    scan_dispatch_slice_for_write_controls,
)
from dispatch.execution_gate import adapter_supports_execution  # noqa: E402


PHASE_3_4_MODULES = (
    "dispatch/worktree_allocator.py",
    "dispatch/worktree_registry.py",
    "dispatch/approval_signing.py",
    "dispatch/approval_replay.py",
    "dispatch/execution_gate.py",
)


class Phase34SafetyBoundaryTests(unittest.TestCase):
    def test_only_local_python_exec_test_supports_execution(self) -> None:
        registry = yaml.safe_load(
            (REPO_ROOT / "agents" / "adapter_registry.yaml").read_text(encoding="utf-8")
        )
        execution_capable: list[str] = []
        for adapter in registry["adapters"]:
            if adapter.get("supports_execution"):
                execution_capable.append(adapter["id"])
            else:
                self.assertFalse(adapter_supports_execution(adapter), adapter["id"])

        expected = (
            ["codex-restricted", "local-python-exec-test"]
            if (REPO_ROOT / "dispatch" / "codex_activation_gate.py").is_file()
            else ["local-python-exec-test"]
        )
        self.assertEqual(sorted(execution_capable), sorted(expected))

    def test_phase34_modules_never_use_shell_true(self) -> None:
        for rel in PHASE_3_4_MODULES:
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), rel)
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", source, rel)
            if "subprocess.run" in source:
                self.assertIn("shell=False", source, rel)

    def _dispatch_to_health_slice(self) -> str:
        source = (REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        start = source.find("TAB PANEL: DISPATCH")
        end = source.find("TAB PANEL: HEALTH")
        self.assertGreaterEqual(start, 0, "DISPATCH tab marker missing")
        self.assertGreater(end, start, "HEALTH tab marker missing after DISPATCH")
        return source[start:end]

    def test_dashboard_has_no_execute_controls(self) -> None:
        dispatch_section = self._dispatch_to_health_slice()
        for forbidden in ("Execute button", "Approve button", "Launch agent", "Run MCP"):
            self.assertNotIn(forbidden, dispatch_section)
        self.assertIn("Read-only", dispatch_section)
        findings = scan_dispatch_slice_for_write_controls(dispatch_section)
        self.assertEqual(
            findings,
            [],
            msg=f"unexpected write controls in DISPATCH→HEALTH slice: {findings}",
        )

    def test_execution_runs_filter_uses_semantic_get_submit_button(self) -> None:
        """GET-form submit is allowed; Execution Runs must use semantic button (not JS anchor)."""
        dispatch_section = self._dispatch_to_health_slice()
        self.assertIn('id="execution-runs-filter-form"', dispatch_section)
        # Semantic button restored (no onclick form.submit anchor dodge)
        self.assertIn(
            '<button type="submit" class="filter-button">Apply</button>',
            dispatch_section,
        )
        self.assertNotIn(
            "execution-runs-filter-form').submit()",
            dispatch_section,
        )
        submits = find_submit_controls(dispatch_section)
        get_submits = [s for s in submits if s[0] == "GET"]
        self.assertTrue(get_submits, "expected at least one GET-form submit in slice")
        findings = scan_dispatch_slice_for_write_controls(dispatch_section)
        self.assertEqual(findings, [])


class SafetyScannerPrecisionTests(unittest.TestCase):
    """Scanner unit tests: GET submit allowed; POST/write submit flagged."""

    def test_get_form_submit_is_allowed(self) -> None:
        html = """
        <form method="GET" action="/">
          <input type="text" name="q">
          <button type="submit" class="filter-button">Apply</button>
        </form>
        """
        findings = scan_dispatch_slice_for_write_controls(html)
        self.assertEqual(findings, [])

    def test_get_form_default_method_is_allowed(self) -> None:
        html = """
        <form action="/">
          <button type="submit">Go</button>
        </form>
        """
        findings = scan_dispatch_slice_for_write_controls(html)
        self.assertEqual(findings, [])

    def test_post_form_submit_is_flagged(self) -> None:
        html = """
        <form method="POST" action="/create_task">
          <button type="submit" class="form-submit-btn">Create</button>
        </form>
        """
        findings = scan_dispatch_slice_for_write_controls(html)
        self.assertTrue(any(f.kind == "write_form_submit" for f in findings), findings)

    def test_execute_label_is_flagged(self) -> None:
        html = '<div>Execute button</div>'
        findings = scan_dispatch_slice_for_write_controls(html)
        self.assertTrue(any(f.kind == "forbidden_label" for f in findings), findings)

    def test_mixed_get_ok_post_flagged(self) -> None:
        html = """
        <form method="GET"><button type="submit">Filter</button></form>
        <form method="POST"><button type="submit">Write</button></form>
        """
        findings = scan_dispatch_slice_for_write_controls(html)
        self.assertEqual(len([f for f in findings if f.kind == "write_form_submit"]), 1)
        self.assertFalse(any("GET" in f.detail for f in findings))


if __name__ == "__main__":
    unittest.main()
