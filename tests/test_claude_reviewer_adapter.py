"""Unit tests for headless Claude reviewer adapter (no live Claude)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.assignment_channel import (  # noqa: E402
    claim_assignment,
    complete_assignment,
    read_assignment,
    write_assignment,
)
from orchestrator.claude_reviewer_adapter import (  # noqa: E402
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    STATE_BLOCKED_AUTH,
    STATE_COMPLETED,
    STATE_INVALID_OUTPUT,
    STATE_RUNNING,
    UNSAFE_FLAGS,
    ClaudeReviewerAdapter,
    ReviewRequest,
    build_claude_review_plan,
    classify_reviewer_failure,
)
from orchestrator.review_dispatcher import (  # noqa: E402
    apply_verdict,
    create_review_request,
    process_one_review,
    try_acquire_review_lease,
)
from orchestrator.review_schema import (  # noqa: E402
    parse_review_stdout,
    validate_review_payload,
)


def _valid_verdict(**overrides):
    base = {
        "verdict": "accepted",
        "summary": "Looks good",
        "repository_integrity": {
            "verified": True,
            "branch": "agent/composer/demo",
            "local_sha": "a" * 40,
            "remote_sha": "a" * 40,
        },
        "tests": [{"command": "python scripts/validate.py", "exit_code": 0, "result": "ok"}],
        "findings": [],
        "required_changes": [],
        "next_assignment": {
            "required": False,
            "task_id": None,
            "goal": None,
            "assigned_to": None,
        },
    }
    base.update(overrides)
    return base


class FakeProcess:
    def __init__(self, pid: int = 4242, exit_code: int = 0, stdout: str = "", stderr: str = ""):
        self.pid = pid
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self._polled = False
        self.killed = False
        self.stdin = None  # launch_process may write plan.stdin_text here

    def poll(self):
        self._polled = True
        return self._exit_code

    def wait(self, timeout=None):
        del timeout
        return self._exit_code

    def kill(self):
        self.killed = True


class SchemaTests(unittest.TestCase):
    def test_valid_acceptance(self) -> None:
        v, e = validate_review_payload(_valid_verdict())
        self.assertEqual(e, [])
        self.assertEqual(v.verdict, "accepted")

    def test_remote_less_target_allows_missing_or_null_remote_sha(self) -> None:
        missing = _valid_verdict()
        missing["repository_integrity"].pop("remote_sha")
        verdict, errors = validate_review_payload(missing)
        self.assertEqual(errors, [])
        self.assertEqual(verdict.verdict, "accepted")

        null_remote = _valid_verdict(
            repository_integrity={
                "verified": True,
                "branch": "agent/composer/demo",
                "local_sha": "a" * 40,
                "remote_sha": None,
            }
        )
        verdict, errors = validate_review_payload(null_remote)
        self.assertEqual(errors, [])
        self.assertEqual(verdict.verdict, "accepted")

    def test_non_empty_malformed_remote_sha_is_rejected(self) -> None:
        verdict, errors = validate_review_payload(
            _valid_verdict(
                repository_integrity={
                    "verified": True,
                    "branch": "agent/composer/demo",
                    "local_sha": "a" * 40,
                    "remote_sha": "not-a-sha",
                }
            )
        )
        self.assertIsNone(verdict)
        self.assertIn("repository_integrity.remote_sha must be 40-char hex", errors)

    def test_valid_request_changes(self) -> None:
        v, e = validate_review_payload(
            _valid_verdict(
                verdict="changes_requested",
                summary="needs fixes",
                required_changes=["fix handoff SHAs"],
                repository_integrity={
                    "verified": False,
                    "branch": "b",
                    "local_sha": "a" * 40,
                    "remote_sha": "b" * 40,
                },
            )
        )
        self.assertEqual(e, [])
        self.assertEqual(v.verdict, "changes_requested")

    def test_valid_rejection(self) -> None:
        v, e = validate_review_payload(
            _valid_verdict(
                verdict="rejected",
                summary="out of scope",
                repository_integrity={
                    "verified": False,
                    "branch": "b",
                    "local_sha": "a" * 40,
                    "remote_sha": "b" * 40,
                },
            )
        )
        self.assertEqual(e, [])

    def test_malformed_output(self) -> None:
        v, e = validate_review_payload({"verdict": "maybe"})
        self.assertIsNone(v)
        self.assertTrue(e)

    def test_parse_claude_envelope(self) -> None:
        payload = _valid_verdict()
        envelope = {"type": "result", "result": json.dumps(payload), "session_id": "sess-1"}
        v, e = parse_review_stdout(json.dumps(envelope))
        self.assertEqual(e, [])
        self.assertEqual(v.verdict, "accepted")

    def test_parse_claude_envelope_nested_object(self) -> None:
        payload = _valid_verdict()
        envelope = {"type": "result", "result": payload, "session_id": "sess-2"}
        v, e = parse_review_stdout(json.dumps(envelope))
        self.assertEqual(e, [])
        self.assertEqual(v.verdict, "accepted")

    def test_parse_stream_json_result_after_activity_events(self) -> None:
        stream = "\n".join([
            json.dumps({"type": "system", "session_id": "sess-stream"}),
            json.dumps({"type": "assistant", "message": {"content": "working"}}),
            json.dumps({"type": "result", "structured_output": _valid_verdict(), "session_id": "sess-stream"}),
        ])
        verdict, errors = parse_review_stdout(stream)
        self.assertEqual(errors, [])
        self.assertEqual(verdict.verdict, "accepted")

    def test_parse_non_json_prose_captures_stdout(self) -> None:
        prose = "I don't see an actual task or question in your message yet"
        envelope = {"type": "result", "result": prose, "session_id": "sess-x"}
        v, e = parse_review_stdout(json.dumps(envelope))
        self.assertIsNone(v)
        self.assertTrue(any("non-JSON prose" in err for err in e))
        self.assertTrue(any("stdout_capture:" in err for err in e))
        self.assertTrue(any("don't see an actual task" in err for err in e))

    def test_parse_raw_non_json_captures_stdout(self) -> None:
        v, e = parse_review_stdout("Hello, how can I help you today?")
        self.assertIsNone(v)
        self.assertTrue(any("stdout_capture:" in err for err in e))


class ArgvPolicyTests(unittest.TestCase):
    def test_claude_argv_restricted_tools_shell_false_ready(self) -> None:
        req = ReviewRequest(
            assignment_id="a1",
            task_id="T1",
            branch="b",
            local_sha="a" * 40,
            remote_sha="a" * 40,
            handoff_path="handoffs/x.md",
            cwd="C:/repo",
        )
        multiline = "line1\nline2\nRULES:\n- do not edit"
        plan = build_claude_review_plan(
            request=req,
            prompt=multiline,
            claude_executable="C:/tools/claude.exe",
            version_runner=lambda *a, **k: type("R", (), {"stdout": "2.1.150\n", "stderr": ""})(),
        )
        self.assertTrue(plan.ok)
        joined = " ".join(plan.argv)
        self.assertIn("-p", plan.argv)
        # Prompt must NOT be an argv element (Windows cmd.exe multiline hazard).
        self.assertNotIn(multiline, plan.argv)
        self.assertFalse(any("\n" in part for part in plan.argv))
        self.assertEqual(plan.stdin_text, multiline)
        self.assertIn("<prompt:stdin>", plan.command_redacted)
        self.assertIn("--permission-mode", plan.argv)
        self.assertIn("dontAsk", plan.argv)
        self.assertIn("--json-schema", plan.argv)
        self.assertIn("--output-format", plan.argv)
        self.assertIn("stream-json", plan.argv)
        self.assertIn("--verbose", plan.argv)
        self.assertIn("Read", joined)
        self.assertIn("Glob", joined)
        self.assertIn("Grep", joined)
        self.assertNotIn("Edit", ",".join(ALLOWED_TOOLS))
        self.assertIn("Edit", DISALLOWED_TOOLS)
        self.assertIn("Write", DISALLOWED_TOOLS)
        for flag in plan.argv:
            self.assertNotIn(flag, UNSAFE_FLAGS)
        self.assertNotIn("--dangerously-skip-permissions", plan.argv)
        self.assertNotIn("--continue", plan.argv)

    def test_auth_and_quota_classification(self) -> None:
        st, _ = classify_reviewer_failure(
            exit_code=1,
            stdout="",
            stderr="Failed to authenticate. API Error: 401 OAuth access token has been revoked.",
            timed_out=False,
        )
        self.assertEqual(st, STATE_BLOCKED_AUTH)
        st2, _ = classify_reviewer_failure(
            exit_code=1, stdout="rate limit exceeded", stderr="", timed_out=False
        )
        self.assertEqual(st2, "blocked_quota")
        st3, _ = classify_reviewer_failure(
            exit_code=None, stdout="", stderr="", timed_out=True
        )
        self.assertEqual(st3, "timed_out")

    def test_auth_keywords_in_successful_verdict_body_are_not_auth_failure(self) -> None:
        """Review text often cites historical OAuth blockers; exit 0 + success envelope is OK."""
        payload = _valid_verdict(
            summary="Handoff documents prior 401 OAuth token revoked; auth is fixed now."
        )
        envelope = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "api_error_status": None,
                "result": json.dumps(payload),
                "structured_output": payload,
            }
        )
        st, detail = classify_reviewer_failure(
            exit_code=0, stdout=envelope, stderr="", timed_out=False
        )
        self.assertEqual(st, STATE_COMPLETED, detail)

    def test_parse_structured_output_field(self) -> None:
        payload = _valid_verdict(summary="via structured_output")
        envelope = {
            "type": "result",
            "result": "see structured_output",
            "structured_output": payload,
            "session_id": "s1",
        }
        v, e = parse_review_stdout(json.dumps(envelope))
        self.assertEqual(e, [])
        self.assertEqual(v.summary, "via structured_output")


class ReviewFlowFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "repo"
        for rel in (
            "runtime/dispatch/assignments/inbox",
            "runtime/dispatch/assignments/claims",
            "runtime/dispatch/assignments/outbox",
            "runtime/dispatch/review_requests",
            "runtime/dispatch/reviews",
            "runtime/dispatch/supervisor_leases",
            "runtime/dispatch/pokes/orchestrator",
            "runtime/dispatch/wake_queue/composer",
            "handoffs",
            "docs",
            "tasks/active",
            "agents",
        ):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "agents" / "adapter_registry.yaml").write_text("adapters: []\n", encoding="utf-8")
        (self.root / "agents" / "composer_restricted_adapter.yaml").write_text(
            "wake:\n  enabled: true\n  mechanism: physical_supervisor\n  command_or_path: scripts/run_orchestrator.py\n",
            encoding="utf-8",
        )
        (self.root / "handoffs" / "T-DEMO__composer__to__claude.md").write_text(
            "# handoff\n", encoding="utf-8"
        )
        path, errors = write_assignment(
            self.root,
            task_id="T-DEMO",
            title="Demo",
            goal="docs only",
            base_branch="main",
            base_sha="b" * 40,
            allowed_paths=["docs/**", "handoffs/**"],
            forbidden_operations=["deploy", "git_merge"],
            acceptance_criteria=["done"],
            verification_commands=["python scripts/validate.py"],
            assigned_by="claude",
            assigned_to="composer",
            task_path="tasks/active/T-DEMO.yaml",
            adapter_id="composer-restricted",
            execution_route="composer_local_builder",
            new_branch="agent/composer/demo",
            handoff_path="handoffs/T-DEMO__composer__to__claude.md",
            assignment_id="assign-demo-review",
        )
        self.assertIsNotNone(path, errors)
        self.assignment_id = "assign-demo-review"
        claim_assignment(self.root, self.assignment_id, sync_task_yaml=False)
        complete_assignment(
            self.root,
            self.assignment_id,
            handoff_path="handoffs/T-DEMO__composer__to__claude.md",
            branch_name="agent/composer/demo",
            branch_tip_sha="a" * 40,
            sync_task_yaml=False,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_one_review_request_idempotent(self) -> None:
        first, e1 = create_review_request(self.root, self.assignment_id)
        second, e2 = create_review_request(self.root, self.assignment_id)
        self.assertEqual(e1, [])
        self.assertEqual(e2, [])
        self.assertEqual(first["assignment_id"], second["assignment_id"])
        self.assertTrue(second.get("idempotent_replay"))

    def test_review_lease(self) -> None:
        ok, reason = try_acquire_review_lease(
            self.root, assignment_id="x", review_run_id="r1", max_concurrency=1
        )
        self.assertTrue(ok, reason)
        ok2, reason2 = try_acquire_review_lease(
            self.root, assignment_id="y", review_run_id="r2", max_concurrency=1
        )
        self.assertFalse(ok2)
        self.assertIn("capacity", reason2)

    def test_handoff_missing_blocks_request(self) -> None:
        # Create assignment without handoff after complete
        path, _ = write_assignment(
            self.root,
            task_id="T-NOH",
            title="No handoff",
            goal="x",
            base_sha="c" * 40,
            assigned_by="claude",
            assigned_to="composer",
            assignment_id="assign-no-handoff",
            handoff_path="",
            new_branch="agent/composer/noh",
        )
        claim_assignment(self.root, "assign-no-handoff", sync_task_yaml=False)
        complete_assignment(
            self.root,
            "assign-no-handoff",
            handoff_path="",
            branch_name="agent/composer/noh",
            branch_tip_sha="d" * 40,
            sync_task_yaml=False,
        )
        # force empty handoff on record + outbox
        rec, _ = read_assignment(self.root, "assign-no-handoff")
        assert rec is not None
        rec.handoff_path = ""
        from dispatch.assignment_channel import _write_inbox_record, outbox_dir
        from dispatch.atomic_io import atomic_write_json

        _write_inbox_record(self.root, rec)
        out_path = outbox_dir(self.root) / "assign-no-handoff.json"
        if out_path.is_file():
            data = json.loads(out_path.read_text(encoding="utf-8"))
            data["handoff_path"] = ""
            atomic_write_json(out_path, data)
        payload, errors = create_review_request(self.root, "assign-no-handoff")
        self.assertIsNone(payload)
        self.assertTrue(any("handoff" in e for e in errors))

    def test_process_review_with_fake_claude_accept(self) -> None:
        payload = _valid_verdict()
        envelope = json.dumps(
            {"type": "result", "result": json.dumps(payload), "session_id": "sess-abc"}
        )
        seen: dict = {}

        def popen(argv, **kwargs):
            seen["argv"] = list(argv)
            seen["stdin"] = kwargs.get("stdin")
            stdout = kwargs.get("stdout")
            if hasattr(stdout, "write"):
                stdout.write(envelope)
                stdout.flush()
            return FakeProcess(pid=9090, exit_code=0)

        adapter = ClaudeReviewerAdapter(
            self.root, claude_executable=sys.executable, popen=popen
        )
        report = process_one_review(
            self.root,
            assignment_id=self.assignment_id,
            adapter=adapter,
            timeout_seconds=30,
            apply=True,
        )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["pid"], 9090)
        self.assertEqual(report["verdict"], "accepted")
        rec, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(rec.status, "accepted")
        # Launch used stdin pipe for the prompt; argv has no multiline body.
        self.assertIsNotNone(seen.get("stdin"))
        self.assertFalse(any("\n" in str(a) for a in seen.get("argv") or []))

    def test_stream_intermediate_events_only_terminal_result_is_recorded(self) -> None:
        payload = _valid_verdict(summary="terminal stream result")
        events = []
        for index in range(25):
            events.extend(
                [
                    {"type": "text", "text": f"working {index}"},
                    {"type": "thinking", "text": "checking"},
                    {"type": "tool_use", "name": "Read", "input": {}},
                    {"type": "tool_result", "content": "ok"},
                    {"type": "user", "message": {"content": "continue"}},
                    {"type": "item.started", "item": {"kind": "review"}},
                    {"type": "item.completed", "structured_output": {"verdict": ""}},
                ]
            )
        events.append(
            {
                "type": "result",
                "structured_output": payload,
                "session_id": "sess-stream-terminal",
            }
        )
        stream = "\n".join(json.dumps(event) for event in events)

        def popen(argv, **kwargs):
            del argv
            stdout = kwargs.get("stdout")
            if hasattr(stdout, "write"):
                stdout.write(stream)
                stdout.flush()
            return FakeProcess(pid=9191, exit_code=0)

        adapter = ClaudeReviewerAdapter(
            self.root, claude_executable=sys.executable, popen=popen
        )
        report = process_one_review(
            self.root,
            assignment_id=self.assignment_id,
            adapter=adapter,
            timeout_seconds=30,
            apply=True,
        )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["verdict"], "accepted")
        self.assertNotEqual(report["status"], STATE_INVALID_OUTPUT)

    def test_stream_without_terminal_result_is_invalid_with_bounded_blocker(self) -> None:
        events = []
        for index in range(60):
            events.append({"type": "text", "text": f"working {index}"})
            events.append({"type": "item.completed", "structured_output": _valid_verdict()})
        stream = "\n".join(json.dumps(event) for event in events)

        def popen(argv, **kwargs):
            del argv
            stdout = kwargs.get("stdout")
            if hasattr(stdout, "write"):
                stdout.write(stream)
                stdout.flush()
            return FakeProcess(pid=9292, exit_code=0)

        adapter = ClaudeReviewerAdapter(
            self.root, claude_executable=sys.executable, popen=popen
        )
        report = process_one_review(
            self.root,
            assignment_id=self.assignment_id,
            adapter=adapter,
            timeout_seconds=30,
            apply=True,
        )
        self.assertEqual(report["status"], STATE_INVALID_OUTPUT)
        blocker = report["blocked_reason"]
        self.assertLess(len(blocker), 1200)
        self.assertNotIn("invalid verdict: ''", blocker)
        rec, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(rec.status, "awaiting_review")

    def test_builder_stays_awaiting_review_on_auth_failure(self) -> None:
        def popen(argv, **kwargs):
            stderr = kwargs.get("stderr")
            if hasattr(stderr, "write"):
                stderr.write("401 OAuth access token has been revoked\n")
                stderr.flush()
            return FakeProcess(pid=111, exit_code=1)

        adapter = ClaudeReviewerAdapter(
            self.root, claude_executable=sys.executable, popen=popen
        )
        report = process_one_review(
            self.root,
            assignment_id=self.assignment_id,
            adapter=adapter,
            timeout_seconds=30,
            apply=True,
        )
        self.assertEqual(report["status"], STATE_BLOCKED_AUTH)
        self.assertEqual(report["assignment_status"], "awaiting_review")
        rec, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(rec.status, "awaiting_review")

    def test_invalid_structured_output_keeps_awaiting_review(self) -> None:
        def popen(argv, **kwargs):
            stdout = kwargs.get("stdout")
            if hasattr(stdout, "write"):
                stdout.write(json.dumps({"type": "result", "result": "not json verdict"}))
                stdout.flush()
            return FakeProcess(pid=222, exit_code=0)

        adapter = ClaudeReviewerAdapter(
            self.root, claude_executable=sys.executable, popen=popen
        )
        report = process_one_review(
            self.root,
            assignment_id=self.assignment_id,
            adapter=adapter,
            apply=True,
        )
        self.assertIn(report["status"], {STATE_INVALID_OUTPUT, "invalid_structured_output"})
        rec, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(rec.status, "awaiting_review")

    def test_changes_requested_wakes_composer(self) -> None:
        verdict, _ = validate_review_payload(
            _valid_verdict(
                verdict="changes_requested",
                summary="fix SHAs",
                required_changes=["regenerate verification block"],
                repository_integrity={
                    "verified": False,
                    "branch": "agent/composer/demo",
                    "local_sha": "a" * 40,
                    "remote_sha": "b" * 40,
                },
            )
        )
        applied, errors = apply_verdict(
            self.root, assignment_id=self.assignment_id, verdict=verdict, wake_composer=True
        )
        # Task YAML sync may warn in fixture without task file — non-fatal.
        self.assertTrue(all("not found" in e or e == "" for e in errors) or errors == [])
        self.assertEqual(applied["resolution"], "changes_requested")
        self.assertIsNotNone(applied.get("wake"))
        wake_files = list(
            (self.root / "runtime" / "dispatch" / "wake_queue" / "composer").glob("*.json")
        )
        self.assertTrue(wake_files)
        rec, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(rec.status, "changes_requested")

    def test_fresh_session_default_no_continue(self) -> None:
        req = ReviewRequest(
            assignment_id="a",
            task_id="t",
            branch="b",
            local_sha="a" * 40,
            remote_sha="a" * 40,
            handoff_path="h.md",
            cwd=str(self.root),
        )
        plan = build_claude_review_plan(
            request=req,
            prompt="p",
            claude_executable="claude",
            version_runner=lambda *a, **k: type("R", (), {"stdout": "2.1.150\n", "stderr": ""})(),
        )
        self.assertNotIn("--continue", plan.argv)
        # resume only when explicitly set
        req.resume_session_id = "019f-test-session"
        plan2 = build_claude_review_plan(
            request=req,
            prompt="p",
            claude_executable="claude",
            version_runner=lambda *a, **k: type("R", (), {"stdout": "2.1.150\n", "stderr": ""})(),
        )
        self.assertIn("--resume", plan2.argv)


if __name__ == "__main__":
    unittest.main()
