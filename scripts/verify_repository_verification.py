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
    parse_verification_block,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a v2 handoff Repository Verification block")
    parser.add_argument("handoff", type=Path, help="Path to handoff markdown file")
    parser.add_argument(
        "--head",
        default=None,
        help="Actual HEAD SHA (default: git rev-parse HEAD)",
    )
    args = parser.parse_args()

    path = args.handoff if args.handoff.is_absolute() else REPO_ROOT / args.handoff
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

    head_for_check = actual_head
    final_recorded = verification.get("final_head_sha", "")
    if final_recorded and actual_head.lower() != final_recorded.lower():
        tip_delta = git_changed_files_since(final_recorded, actual_head, str(REPO_ROOT))
        if tip_delta is not None and tip_delta and all(
            p.replace("\\", "/").startswith("handoffs/") for p in tip_delta
        ):
            head_for_check = final_recorded

    result = validate_repository_verification(
        verification,
        actual_head_sha=head_for_check,
        changed_files_after_tests=changed,
        rel=rel,
    )
    if head_for_check != actual_head:
        print(
            f"Note: actual HEAD ({actual_head}) is one handoff-only commit ahead of "
            f"recorded final_head_sha ({final_recorded})",
            file=sys.stderr,
        )

    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"Error: {error}", file=sys.stderr)
    if result.post_test_violations:
        print("Post-test violations:", ", ".join(result.post_test_violations), file=sys.stderr)

    print(f"Status: {result.status}")
    if result.status == "verified":
        return 0
    if result.status == "structurally_valid":
        print("Git context supplied but verification incomplete.", file=sys.stderr)
        return 1 if result.errors else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())