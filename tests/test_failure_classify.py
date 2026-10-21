"""Provider errors must be distinguished from arbitrary builder output."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from orchestrator.failure_classify import classify_process_output


class StructuredClassificationTests(unittest.TestCase):
    def classify(self, stdout="", stderr="", exit_code=0, **kwargs):
        return classify_process_output(agent="codex", adapter="codex-restricted",
                                       stdout=stdout, stderr=stderr,
                                       exit_code=exit_code, **kwargs)

    def test_drill_excerpt(self):
        stdout = Path(__file__).with_name("fixtures").joinpath(
            "quota_recovery_drill_excerpt.txt").read_text(encoding="utf-8")
        self.assertEqual(self.classify(stdout).process_state, "completed")

    def test_narration_and_tool_output_are_never_provider_errors(self):
        for event in (
            {"type": "tool_use", "path": r"C:\t-drill-quota\DRILL_QUOTA_RECOVERY.md"},
            {"type": "tool_result", "is_error": True, "error": "quota 402 max turns"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "quota max turns rate limit"}},
            {"type": "assistant", "message": "authentication 401 quota"},
            {"type": "result", "is_error": False, "result": "max turns rate limit quota retry-after: 60"},
            {"is_error": False, "result": "max turns rate limit quota"},
            {"type": "tool_result", "num_turns": 5, "max_turns": 5, "stop_reason": "max_turns"},
            {"type": [], "message": "quota max turns"},
        ):
            for code in (0, 1):
                with self.subTest(event=event, code=code):
                    result = self.classify(json.dumps(event), exit_code=code)
                    self.assertEqual(result.process_state, "completed" if code == 0 else "failed")
                    self.assertIsNone(result.retry_after)

    def test_structured_provider_errors(self):
        for event, expected in (
            ({"type": "result", "is_error": True, "result": "API error (status 402): balance exhausted"}, "blocked_quota"),
            ({"is_error": True, "result": "API error (status 402): balance exhausted"}, "blocked_quota"),
            ({"type": "result", "error": {"status": 402, "message": "payment required"}}, "blocked_quota"),
            ({"type": "turn.failed", "error": {"message": "usage limit; retry-after: 60"}}, "blocked_quota"),
            ({"type": "error", "message": "usage limit"}, "blocked_quota"),
            ({"type": "result", "is_error": True, "result": "usage limit while investigating max turns"}, "blocked_quota"),
            ({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "401 unauthorized"}, "blocked_authentication"),
            ({"type": "turn.failed", "error": {"message": "unrelated provider failure"}}, "failed"),
            ({"type": "turn.failed"}, "failed"),
        ):
            for code in (0, 1):
                with self.subTest(event=event, code=code):
                    self.assertEqual(self.classify(json.dumps(event), exit_code=code).process_state, expected)

    def test_retry_after_uses_only_error_channels(self):
        now = datetime(2026, 10, 22, tzinfo=timezone.utc)
        with patch("orchestrator.failure_classify._now", return_value=now):
            result = self.classify(
                'retry-after: 999\n' + json.dumps({"type": "turn.failed", "error": {"message": "usage limit; retry-after: 60"}}))
        self.assertEqual(result.retry_after, "2026-10-22T00:01:00Z")
        self.assertTrue(result.retry_eligible)
        with patch("orchestrator.failure_classify._now", return_value=now):
            nested = self.classify(json.dumps({"type": "error", "error": {
                "message": "usage limit", "retry_after": 60}}))
        self.assertEqual(nested.retry_after, result.retry_after)

    def test_max_turns_structured_signals(self):
        for event in (
            {"type": "result", "subtype": "error_max_turns"},
            {"type": "result", "stop_reason": "max_turns"},
            {"type": "result", "num_turns": 5, "max_turns": 5},
        ):
            with self.subTest(event=event):
                result = self.classify(json.dumps(event))
                self.assertEqual(result.process_state, "max_turns")
                self.assertTrue(result.retry_eligible)

    def test_stderr_and_plain_stdout(self):
        self.assertEqual(self.classify("usage limit exceeded", exit_code=1).process_state, "blocked_quota")
        self.assertEqual(self.classify(stderr="quota max turns 401", exit_code=0).process_state, "completed")
        self.assertEqual(self.classify(stderr="unrelated failure", exit_code=1).process_state, "failed")
        self.assertEqual(self.classify("API error (status 402): exhausted", exit_code=1).process_state, "blocked_quota")
        self.assertEqual(self.classify(stderr='{"type":"error","message":"401 unauthorized"}').process_state, "blocked_authentication")

    def test_real_provider_formats(self):
        fixtures = Path(__file__).with_name("fixtures") / "real_provider_errors"
        for name, agent, code, expected in (
            ("claude_401.txt", "claude", 1, "blocked_authentication"),
            ("claude_oauth_expired.txt", "claude", 1, "blocked_authentication"),
            ("grok_402.txt", "composer", 1, "blocked_quota"),
            ("codex_usage_limit.txt", "codex", 1, "blocked_quota"),
            ("successful_narration.txt", "codex", 0, "completed"),
        ):
            stdout = (fixtures / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                result = classify_process_output(
                    agent=agent, adapter=f"{agent}-restricted",
                    stdout=stdout, exit_code=code,
                )
                self.assertEqual(result.process_state, expected)
                # Plain narration cannot override a successful exit.
                if name.startswith("claude_"):
                    self.assertEqual(self.classify(stdout).process_state, "completed")

    def test_mixed_error_channels_exclude_tool_and_item_content(self):
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                payload = '\n'.join((
                    json.dumps({"type": "tool_result", "is_error": True,
                                "error": "401 quota max turns"}),
                    json.dumps({"type": "agent_message", "text": "401 quota max turns"}),
                    json.dumps({"type": "item.completed", "item": {
                        "type": "error", "message": "401 quota max turns"}}),
                    "unrelated fatal failure",
                ))
                self.assertEqual(self.classify(**{stream: payload}, exit_code=1).process_state, "failed")

    def test_plain_stdout_max_turns_only_on_failed_exit(self):
        for code, expected in ((0, "completed"), (1, "max_turns")):
            with self.subTest(code=code):
                self.assertEqual(self.classify("Maximum turns reached", exit_code=code).process_state, expected)

    def test_pretty_json_and_jsonl_errors(self):
        error = {"type": "result", "is_error": True, "error": {"status": 402}}
        for stdout in (json.dumps(error, indent=2),
                       '{"type":"turn.started"}\n' + json.dumps(error)):
            self.assertEqual(self.classify(stdout).process_state, "blocked_quota")

    def test_required_mcp_uses_error_channels(self):
        options = {"required_mcp_servers": ["github"]}
        self.assertEqual(self.classify("github quota max turns", **options).process_state, "completed")
        self.assertEqual(self.classify(stderr="MCP github connection failed", exit_code=1, **options).process_state, "blocked_external")
