"""Phase 3.9.5 — per-assignment MCP isolation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import validate_assignment_payload  # noqa: E402
from dispatch.codex_adapter import (  # noqa: E402
    CODEX_EXECUTABLE,
    append_codex_prompt,
    build_codex_command,
    build_codex_exec_options,
    load_codex_restricted_adapter,
    validate_codex_argv_contract,
)
from dispatch.mcp_isolation import (  # noqa: E402
    CODEX_EMPTY_MCP_SERVERS_OVERRIDE,
    CODEX_IGNORE_USER_CONFIG_FLAG,
    GROK_MCP_ISOLATION_GAP,
    build_codex_mcp_isolation_flags,
    build_grok_mcp_isolation_note,
    classify_required_mcp_failure,
    extract_required_mcp_servers,
    normalize_required_mcp_servers,
    simulate_unlisted_mcp_cannot_abort,
    validate_required_mcp_servers,
)
from orchestrator.agent_launcher import build_grok_launch_plan  # noqa: E402
from orchestrator.failure_classify import classify_process_output  # noqa: E402
from orchestrator.runtime_store import STATE_BLOCKED_EXTERNAL  # noqa: E402


class RequiredMcpServersSchemaTests(unittest.TestCase):
    def test_default_empty(self) -> None:
        self.assertEqual(normalize_required_mcp_servers(None), [])
        self.assertEqual(extract_required_mcp_servers({}), [])
        self.assertEqual(extract_required_mcp_servers({"title": "x"}), [])

    def test_top_level_and_execution_paths(self) -> None:
        self.assertEqual(
            extract_required_mcp_servers({"required_mcp_servers": ["github", "exa"]}),
            ["github", "exa"],
        )
        self.assertEqual(
            extract_required_mcp_servers(
                {"execution": {"required_mcp_servers": ["memory"]}}
            ),
            ["memory"],
        )

    def test_validation_rejects_bad_names(self) -> None:
        errors = validate_required_mcp_servers(["ok", "bad name!", ""])
        self.assertTrue(errors)
        self.assertTrue(any("invalid name" in e or "non-empty" in e for e in errors))

    def test_validation_rejects_non_list(self) -> None:
        self.assertTrue(validate_required_mcp_servers("github"))

    def test_assignment_payload_accepts_empty_list(self) -> None:
        payload = {
            "schema_version": "1.0",
            "assignment_id": "assign-test",
            "task_id": "T-TEST",
            "title": "t",
            "goal": "g",
            "base_branch": "main",
            "base_sha": "a" * 40,
            "new_branch": "agent/composer/T-TEST",
            "allowed_paths": ["docs/**"],
            "forbidden_operations": ["deploy"],
            "acceptance_criteria": ["ok"],
            "verification_commands": ["python scripts/validate.py"],
            "timeout": 1800,
            "handoff_path": "handoffs/T-TEST__composer__to__claude.md",
            "assigned_by": "claude",
            "assigned_to": "composer",
            "created_at": "2026-07-17T00:00:00Z",
            "status": "pending",
            "required_mcp_servers": [],
        }
        self.assertEqual(validate_assignment_payload(payload), [])

    def test_assignment_payload_rejects_invalid_mcp_list(self) -> None:
        payload = {
            "schema_version": "1.0",
            "assignment_id": "assign-test",
            "task_id": "T-TEST",
            "title": "t",
            "goal": "g",
            "base_branch": "main",
            "base_sha": "a" * 40,
            "new_branch": "agent/composer/T-TEST",
            "allowed_paths": ["docs/**"],
            "forbidden_operations": ["deploy"],
            "acceptance_criteria": ["ok"],
            "verification_commands": ["python scripts/validate.py"],
            "timeout": 1800,
            "handoff_path": "handoffs/T-TEST__composer__to__claude.md",
            "assigned_by": "claude",
            "assigned_to": "composer",
            "created_at": "2026-07-17T00:00:00Z",
            "status": "pending",
            "required_mcp_servers": "not-a-list",
        }
        errors = validate_assignment_payload(payload)
        self.assertTrue(any("required_mcp_servers" in e for e in errors))


class CodexMcpIsolationFlagTests(unittest.TestCase):
    def test_empty_required_injects_zero_mcp_flags(self) -> None:
        flags, blocked, evidence = build_codex_mcp_isolation_flags([])
        self.assertEqual(blocked, [])
        self.assertIn(CODEX_IGNORE_USER_CONFIG_FLAG, flags)
        self.assertIn(CODEX_EMPTY_MCP_SERVERS_OVERRIDE, flags)
        self.assertEqual(evidence["policy"], "zero_optional_mcp_connections")

    def test_exec_options_include_isolation_before_cd(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        opts = build_codex_exec_options(
            adapter,
            worktree_path="/wt",
            agent_output_path="/wt/out.json",
            required_mcp_servers=[],
        )
        self.assertEqual(opts[0], "exec")
        self.assertIn(CODEX_IGNORE_USER_CONFIG_FLAG, opts)
        self.assertIn(CODEX_EMPTY_MCP_SERVERS_OVERRIDE, opts)
        # Isolation must precede -C so config is applied for the session.
        self.assertLess(opts.index(CODEX_IGNORE_USER_CONFIG_FLAG), opts.index("-C"))

    def test_argv_contract_allows_isolation_flags(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        output_path = "/wt/out.json"
        prompt = "do the work"
        argv = append_codex_prompt(
            [
                CODEX_EXECUTABLE,
                *build_codex_exec_options(
                    adapter,
                    worktree_path="/wt",
                    agent_output_path=output_path,
                    required_mcp_servers=[],
                ),
            ],
            prompt,
        )
        blocked = validate_codex_argv_contract(
            argv, agent_output_path=output_path, prompt=prompt
        )
        self.assertEqual(blocked, [])
        self.assertEqual(argv[-1], prompt)

    def test_rehydrate_simple_required_server(self) -> None:
        flags, blocked, evidence = build_codex_mcp_isolation_flags(
            ["github"],
            user_mcp_servers={
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                }
            },
        )
        self.assertEqual(blocked, [])
        self.assertEqual(evidence["rehydrated_servers"], ["github"])
        self.assertTrue(any(f.startswith("mcp_servers.github=") for f in flags))

    def test_missing_required_server_blocks(self) -> None:
        flags, blocked, _evidence = build_codex_mcp_isolation_flags(
            ["missing-server"],
            user_mcp_servers={},
        )
        self.assertTrue(blocked)
        self.assertIn(CODEX_IGNORE_USER_CONFIG_FLAG, flags)


class UnlistedMcpCannotAbortTests(unittest.TestCase):
    def test_simulated_stale_token_unlisted_cannot_abort(self) -> None:
        proof = simulate_unlisted_mcp_cannot_abort(
            required_mcp_servers=[],
            unlisted_server="supabase",
            unlisted_error=(
                "AuthRequired(AuthRequiredError { error_description: "
                '"Invalid oauth access token" })'
            ),
        )
        self.assertTrue(proof["unlisted_isolated_away"])
        self.assertFalse(proof["can_abort_run"])
        self.assertIn(CODEX_EMPTY_MCP_SERVERS_OVERRIDE, proof["isolation_flags"])
        self.assertIn("cannot abort", proof["proof"])


class RequiredMcpFailureClassificationTests(unittest.TestCase):
    def test_required_mcp_oauth_failure_is_blocked_external(self) -> None:
        stderr = (
            "ERROR rmcp::transport::worker: worker quit with fatal: "
            "AuthRequired(AuthRequiredError { error_description: "
            '"Invalid oauth access token" }) for server github'
        )
        hit = classify_required_mcp_failure(
            required_mcp_servers=["github"],
            stdout="",
            stderr=stderr,
            exit_code=1,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["process_state"], "blocked_external")
        self.assertIn("required MCP failure", hit["detail"])

        classification = classify_process_output(
            agent="codex",
            adapter="codex-restricted",
            exit_code=1,
            stdout="",
            stderr=stderr,
            required_mcp_servers=["github"],
        )
        self.assertEqual(classification.process_state, STATE_BLOCKED_EXTERNAL)
        self.assertEqual(classification.category, "blocked_external")
        self.assertFalse(classification.retry_eligible)

    def test_empty_required_does_not_force_blocked_external_on_generic_fail(self) -> None:
        classification = classify_process_output(
            agent="codex",
            adapter="codex-restricted",
            exit_code=1,
            stdout="",
            stderr="some unrelated compile error",
            required_mcp_servers=[],
        )
        self.assertEqual(classification.category, "failed")


class GrokMcpIsolationGapTests(unittest.TestCase):
    def test_grok_note_documents_gap(self) -> None:
        note = build_grok_mcp_isolation_note([])
        self.assertEqual(note["isolation_mode"], "unsupported")
        self.assertIn("no documented per-invocation", note["gap"])
        self.assertEqual(note["flags"], [])
        self.assertIn("Grok Build CLI", GROK_MCP_ISOLATION_GAP)

    def test_grok_launch_plan_records_gap_without_fake_flags(self) -> None:
        plan = build_grok_launch_plan(
            worktree=REPO_ROOT,
            prompt="hello",
            grok_executable=str(REPO_ROOT / "fake-grok.exe"),
            version_runner=lambda *a, **k: type(
                "P", (), {"stdout": "grok 0.0.0", "stderr": ""}
            )(),
            required_mcp_servers=[],
        )
        self.assertEqual(plan.required_mcp_servers, [])
        self.assertEqual(plan.mcp_isolation.get("isolation_mode"), "unsupported")
        # No invented MCP isolation flags in argv.
        joined = " ".join(plan.argv)
        self.assertNotIn("mcp_servers={}", joined)
        self.assertNotIn("--ignore-user-config", joined)


class CodexCommandPlanIntegrationTests(unittest.TestCase):
    def test_build_codex_command_default_zero_mcp(self) -> None:
        adapter = load_codex_restricted_adapter(REPO_ROOT)
        plan = build_codex_command(
            adapter,
            repo_root=REPO_ROOT,
            worktree_path=str(REPO_ROOT),
            run_id="mcp-iso-test",
            stdout_path="stdout.txt",
            stderr_path="stderr.txt",
            agent_output_path="/wt/out.json",
            timeout_seconds=600,
            cli_version="0.136.0",
            allocation_record=None,
            prompt="Follow instructions",
            required_mcp_servers=[],
        )
        self.assertIn(CODEX_IGNORE_USER_CONFIG_FLAG, plan.argv)
        self.assertIn(CODEX_EMPTY_MCP_SERVERS_OVERRIDE, plan.argv)
        self.assertEqual(plan.required_mcp_servers, [])
        self.assertEqual(plan.mcp_isolation.get("policy"), "zero_optional_mcp_connections")


if __name__ == "__main__":
    unittest.main()
