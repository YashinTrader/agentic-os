#!/usr/bin/env python3
"""Git-backed repository verification for Handoff Protocol v2 blocks."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.repository_verification import (  # noqa: E402
    git_changed_files_since,
    git_is_ancestor,
    load_unittest_artifact,
    parse_verification_block,
    resolve_head_for_verification,
    run_validator_at_head,
    validate_repository_verification,
)


def _git_rev_parse(ref: str = "HEAD") -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except OSError:
        return None
    return None


def _print_result(result) -> None:
    if result.artifact_status:
        label = "verified" if result.artifact_status == "verified" else "failed"
        print(f"Artifact: {label}")
    if result.git_ancestry_status:
        print(f"Git ancestry: {result.git_ancestry_status}")
    if result.post_test_diff_status:
        print(f"Post-test diff: {result.post_test_diff_status}")
    if result.validator_status:
        status = "passed" if result.validator_status == "passed" else "failed"
        print(f"Validator at HEAD: {status}")
        if result.validator_exit_code is not None:
            print(f"Validator exit code: {result.validator_exit_code}")
    print(f"Status: {result.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a v2 handoff Repository Verification block")
    parser.add_argument("handoff", nargs="?", type=Path, default=None, help="Path to handoff markdown file")
    parser.add_argument("--handoff", dest="handoff_opt", type=Path, default=None, help="Path to handoff markdown file")
    parser.add_argument(
        "--head",
        default=None,
        help="Actual HEAD SHA (default: git rev-parse HEAD)",
    )
    parser.add_argument(
        "--skip-validator",
        action="store_true",
        help="Skip validator-at-HEAD subprocess (for tests only)",
    )
    args = parser.parse_args()

    handoff_arg = args.handoff_opt or args.handoff
    if handoff_arg is None:
        print("Handoff path required (positional or --handoff)", file=sys.stderr)
        return 2

    path = handoff_arg if handoff_arg.is_absolute() else REPO_ROOT / handoff_arg
    if not path.exists():
        print(f"Handoff not found: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(REPO_ROOT))
    verification = parse_verification_block(text)
    if not verification:
        print(f"{rel}: no Repository Verification block found", file=sys.stderr)
        return 1

    actual_head = args.head or _git_rev_parse("HEAD")
    if not actual_head:
        print("git rev-parse HEAD failed", file=sys.stderr)
        return 2

    tests_sha = verification.get("tests_commit_sha", "")
    final_head = verification.get("final_head_sha", "")
    changed: list[str] | None = None

    if tests_sha and final_head and tests_sha.lower() != final_head.lower():
        changed = git_changed_files_since(tests_sha, final_head, str(REPO_ROOT))
        if changed is None:
            print("git diff --name-only failed", file=sys.stderr)
            return 2
        ancestor = git_is_ancestor(tests_sha, final_head, str(REPO_ROOT))
        if ancestor is False:
            print(
                f"{rel}: tests_commit_sha ({tests_sha}) is not an ancestor of final_head_sha ({final_head})",
                file=sys.stderr,
            )
            return 1
        if ancestor is None:
            print("git merge-base --is-ancestor unavailable", file=sys.stderr)
            return 2
    else:
        changed = []

    head_for_check = resolve_head_for_verification(actual_head, final_head, str(REPO_ROOT))

    artifact, artifact_exists = load_unittest_artifact(REPO_ROOT)
    validator_result = None if args.skip_validator else run_validator_at_head(REPO_ROOT)

    result = validate_repository_verification(
        verification,
        actual_head_sha=head_for_check,
        changed_files_after_tests=changed,
        rel=rel,
        test_artifact=artifact,
        artifact_exists=artifact_exists,
        artifact_is_ancestor=git_is_ancestor,
        validator_result=validator_result,
        run_artifact_checks=True,
        run_validator_checks=not args.skip_validator,
    )
    if head_for_check != actual_head:
        print(
            f"Note: actual HEAD ({actual_head}) is ahead of recorded final_head_sha ({final_head}); "
            "only allowlisted post-test files differ.",
            file=sys.stderr,
        )

    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"Error: {error}", file=sys.stderr)
    if result.post_test_violations:
        print("Post-test violations:", ", ".join(result.post_test_violations), file=sys.stderr)

    _print_result(result)
    if result.status == "verified":
        return 0
    if result.status == "structurally_valid":
        print("Git context supplied but verification incomplete.", file=sys.stderr)
        return 1 if result.errors else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())