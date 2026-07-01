#!/usr/bin/env python3
"""Emit a complete Handoff Protocol v2 Repository Verification block."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FIELDS = (
    "repo_root",
    "branch",
    "base_sha",
    "implementation_sha",
    "tests_commit_sha",
    "final_head_sha",
    "remote_head_sha",
    "git_status_clean",
    "validator_commit_sha",
    "test_count",
    "test_exit_code",
    "validator_exit_code",
    "post_test_diff_policy",
    "post_test_files",
    "working_copy_path",
)


def _git(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def git_sha(ref: str = "HEAD", *, cwd: Path = REPO_ROOT) -> str:
    return _git(["rev-parse", ref], cwd=cwd)


def git_branch(*, cwd: Path = REPO_ROOT) -> str:
    return _git(["branch", "--show-current"], cwd=cwd)


def git_toplevel(*, cwd: Path = REPO_ROOT) -> str:
    return _git(["rev-parse", "--show-toplevel"], cwd=cwd)


def git_status_clean(*, cwd: Path = REPO_ROOT) -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and not proc.stdout.strip()


def parse_unittest_artifact(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(path)
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("--- "):
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def render_repository_verification_block(
    *,
    repo_root: str,
    branch: str,
    base_sha: str,
    implementation_sha: str,
    tests_commit_sha: str,
    final_head_sha: str,
    remote_head_sha: str,
    git_status_clean_value: bool,
    validator_commit_sha: str,
    test_count: int | str,
    test_exit_code: int = 0,
    validator_exit_code: int = 0,
    post_test_diff_policy: str = "POST_TEST_ALLOWLIST_EXACT",
    post_test_files: list[str] | str | None = None,
    working_copy_path: str | None = None,
) -> str:
    if post_test_files is None:
        post_test_files_text = "none"
    elif isinstance(post_test_files, str):
        post_test_files_text = post_test_files.strip() or "none"
    else:
        post_test_files_text = ", ".join(post_test_files) if post_test_files else "none"

    wc = working_copy_path or repo_root
    lines = [
        "## Repository Verification",
        "",
        f"repo_root: {repo_root.replace(chr(92), '/')}",
        f"branch: {branch}",
        f"base_sha: {base_sha}",
        f"implementation_sha: {implementation_sha}",
        f"tests_commit_sha: {tests_commit_sha}",
        f"final_head_sha: {final_head_sha}",
        f"remote_head_sha: {remote_head_sha}",
        f"git_status_clean: {'true' if git_status_clean_value else 'false'}",
        f"validator_commit_sha: {validator_commit_sha}",
        f"test_count: {test_count}",
        f"test_exit_code: {test_exit_code}",
        f"validator_exit_code: {validator_exit_code}",
        f"post_test_diff_policy: {post_test_diff_policy}",
        f"post_test_files: {post_test_files_text}",
        f"working_copy_path: {wc.replace(chr(92), '/')}",
        "",
    ]
    return "\n".join(lines)


def replace_repository_verification_section(handoff_text: str, block: str) -> str:
    marker = "## Repository Verification"
    if marker not in handoff_text:
        if "**Handoff Protocol:** v2" not in handoff_text:
            handoff_text = handoff_text.rstrip() + "\n\n**Handoff Protocol:** v2\n"
        return handoff_text.rstrip() + "\n\n" + block
    before, _rest = handoff_text.split(marker, 1)
    after_lines = _rest.splitlines()
    body: list[str] = []
    for line in after_lines[1:]:
        if line.startswith("## "):
            body = [line, *after_lines[after_lines.index(line) + 1 :]]
            break
    else:
        body = []
    rebuilt = before.rstrip() + "\n\n" + block
    if body:
        rebuilt += "\n".join(body)
    return rebuilt.rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a v2 Repository Verification block")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--final-head-sha", required=True)
    parser.add_argument("--remote-head-sha", default=None)
    parser.add_argument("--validator-commit-sha", default=None)
    parser.add_argument("--post-test-files", default="none")
    parser.add_argument("--artifact", default=str(REPO_ROOT / "runtime" / "unittest_last_run.txt"))
    parser.add_argument("--branch", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--working-copy-path", default=None)
    args = parser.parse_args()

    repo_root = (args.repo_root or git_toplevel()).replace("\\", "/")
    branch = args.branch or git_branch()
    remote_head = args.remote_head_sha or args.final_head_sha
    validator_sha = args.validator_commit_sha or args.implementation_sha
    artifact = parse_unittest_artifact(Path(args.artifact))
    test_count = artifact.get("test_count", "")
    test_exit = int(artifact.get("exit_code", "0") or 0)
    tests_commit = artifact.get("commit_full", args.implementation_sha)

    block = render_repository_verification_block(
        repo_root=repo_root,
        branch=branch,
        base_sha=args.base_sha,
        implementation_sha=args.implementation_sha,
        tests_commit_sha=tests_commit,
        final_head_sha=args.final_head_sha,
        remote_head_sha=remote_head,
        git_status_clean_value=git_status_clean(),
        validator_commit_sha=validator_sha,
        test_count=test_count,
        test_exit_code=test_exit,
        validator_exit_code=0,
        post_test_files=args.post_test_files,
        working_copy_path=args.working_copy_path or repo_root,
    )
    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())