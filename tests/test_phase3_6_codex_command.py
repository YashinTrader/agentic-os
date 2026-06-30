from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dispatch.codex_adapter import (  # noqa: E402
    CODEX_EXECUTABLE,
    CODEX_OUTPUT_FLAG,
    append_codex_prompt,
    build_codex_exec_options,
    build_codex_command,
    load_codex_restricted_adapter,
    validate_codex_argv_contract,
)


class CodexCommandContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = load_codex_restricted_adapter(REPO_ROOT)
        self.output_path = "/wt/runtime/out/agent-last.txt"
        self.prompt = "Follow instructions in context bundle"
        self.spaced_prompt = "one two three"

    def _base_argv(self, prompt: str | None = None) -> list[str]:
        prompt_arg = prompt if prompt is not None else self.prompt
        return append_codex_prompt(
            [
                CODEX_EXECUTABLE,
                *build_codex_exec_options(
                    self.adapter,
                    worktree_path="/wt",
                    agent_output_path=self.output_path,
                ),
            ],
            prompt_arg,
        )

    def test_o_flag_exactly_once(self) -> None:
        argv = self._base_argv()
        self.assertEqual(argv.count(CODEX_OUTPUT_FLAG), 1)

    def test_token_after_o_is_output_path(self) -> None:
        argv = self._base_argv()
        o_idx = argv.index(CODEX_OUTPUT_FLAG)
        self.assertEqual(argv[o_idx + 1], self.output_path)

    def test_prompt_exactly_once(self) -> None:
        argv = self._base_argv()
        self.assertEqual(argv.count(self.prompt), 1)

    def test_prompt_is_trailing_positional(self) -> None:
        argv = self._base_argv()
        self.assertEqual(argv[-1], self.prompt)

    def test_prompt_does_not_replace_flag_value(self) -> None:
        argv = self._base_argv()
        o_idx = argv.index(CODEX_OUTPUT_FLAG)
        self.assertNotEqual(argv[o_idx + 1], self.prompt)

    def test_output_path_not_prompt(self) -> None:
        argv = self._base_argv()
        o_idx = argv.index(CODEX_OUTPUT_FLAG)
        self.assertNotEqual(argv[o_idx + 1], argv[-1])

    def test_spaced_prompt_single_argv_token(self) -> None:
        argv = self._base_argv(self.spaced_prompt)
        self.assertEqual(argv[-1], self.spaced_prompt)
        self.assertEqual(argv.count(self.spaced_prompt), 1)

    def test_argv_list_not_shell_string(self) -> None:
        argv = self._base_argv()
        self.assertIsInstance(argv, list)
        for token in argv:
            self.assertIsInstance(token, str)

    def test_unknown_option_blocked_by_contract(self) -> None:
        argv = self._base_argv()
        argv.insert(2, "--unknown-flag")
        blocked = validate_codex_argv_contract(
            argv,
            agent_output_path=self.output_path,
            prompt=self.prompt,
        )
        self.assertTrue(blocked)

    def test_ma1_regression_output_path_preserved(self) -> None:
        """Would fail if argv[-1] = prompt overwrote -o value."""
        argv = self._base_argv()
        o_idx = argv.index(CODEX_OUTPUT_FLAG)
        self.assertEqual(argv[o_idx + 1], self.output_path)
        self.assertEqual(argv[-1], self.prompt)

    def test_build_codex_command_argv_shape(self) -> None:
        plan = build_codex_command(
            self.adapter,
            repo_root=REPO_ROOT,
            worktree_path=str(REPO_ROOT),
            run_id="phase3-6-command-test",
            stdout_path="stdout.txt",
            stderr_path="stderr.txt",
            agent_output_path=self.output_path,
            timeout_seconds=600,
            cli_version="0.136.0",
            allocation_record=None,
            prompt=self.prompt,
        )
        self.assertEqual(plan.argv[-1], self.prompt)
        o_idx = plan.argv.index(CODEX_OUTPUT_FLAG)
        self.assertEqual(plan.argv[o_idx + 1], self.output_path)


if __name__ == "__main__":
    unittest.main()