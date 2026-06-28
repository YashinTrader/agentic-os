"""Repository verification helpers for Handoff Protocol v2.

Offline validation checks structure and recorded invariants from handoff text.
Git-backed checks (ancestor relationship, post-test diff) run via CLI or when
callers supply ``changed_files_after_tests`` and ``actual_head_sha``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")

# Conservative post-test allowlist (documentation / verification only).
POST_TEST_ALLOWLIST_PREFIXES = (
    "docs/",
    "handoffs/",
    "tasks/",
)
POST_TEST_ALLOWLIST_EXACT = frozenset({"runtime/unittest_last_run.txt"})

# Paths that invalidate verification if changed after tests_commit_sha.
POST_TEST_FORBIDDEN_PREFIXES = (
    "dispatch/",
    "scripts/",
    "tests/",
    "schemas/",
    "protocol/",
    "agents/",
    "daemon/",
    "dashboard/",
    "orchestrator/",
    "integrations/",
)

REQUIRED_VERIFICATION_FIELDS_V2 = (
    "repo_root:",
    "branch:",
    "base_sha:",
    "implementation_sha:",
    "tests_commit_sha:",
    "final_head_sha:",
    "remote_head_sha:",
    "git_status_clean:",
    "validator_commit_sha:",
    "test_count:",
    "test_exit_code:",
    "validator_exit_code:",
    "post_test_diff_policy:",
    "post_test_files:",
    "working_copy_path:",
)

SHA_VERIFICATION_FIELDS = (
    "base_sha:",
    "implementation_sha:",
    "tests_commit_sha:",
    "final_head_sha:",
    "remote_head_sha:",
    "validator_commit_sha:",
)


@dataclass
class ValidationResult:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    post_test_violations: list[str] = field(default_factory=list)


def verification_field_value(text: str, field_name: str) -> str | None:
    prefix = field_name if field_name.endswith(":") else f"{field_name}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def parse_verification_block(text: str) -> dict[str, str]:
    if "## Repository Verification" not in text:
        return {}
    section = text.split("## Repository Verification", 1)[1]
    # Stop at next level-2 heading.
    lines: list[str] = []
    for line in section.splitlines()[1:]:
        if line.startswith("## "):
            break
        lines.append(line)
    block = "\n".join(lines)
    out: dict[str, str] = {}
    for key in (
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
        "final_head_ref",
        "artifact_parent_sha",
    ):
        val = verification_field_value(block, f"{key}:")
        if val is not None:
            out[key] = val
    return out


def _normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_post_test_allowlisted(path: str) -> bool:
    norm = _normalize_repo_path(path)
    if norm in POST_TEST_ALLOWLIST_EXACT:
        return True
    return any(norm.startswith(prefix) for prefix in POST_TEST_ALLOWLIST_PREFIXES)


def classify_post_test_files(changed_files: list[str]) -> tuple[list[str], list[str]]:
    """Return (allowed, violations) for files changed after tests_commit_sha."""
    allowed: list[str] = []
    violations: list[str] = []
    for raw in changed_files:
        norm = _normalize_repo_path(raw)
        if not norm:
            continue
        if is_post_test_allowlisted(norm):
            allowed.append(norm)
        else:
            violations.append(norm)
    return allowed, violations


def _validate_sha_field(name: str, value: str | None, errors: list[str], rel: str) -> None:
    if value is None:
        return
    if not _SHA40_RE.match(value):
        errors.append(f"{rel}: {name} must be a 40-character hex SHA ({value!r})")


def validate_repository_verification(
    verification: dict[str, Any],
    *,
    actual_head_sha: str | None = None,
    changed_files_after_tests: list[str] | None = None,
    rel: str = "handoff",
) -> ValidationResult:
    """Validate a parsed Repository Verification block.

    Without Git context, structural and recorded invariants are checked and status
    is ``structurally_valid`` or ``failed``. With ``actual_head_sha`` and/or
    ``changed_files_after_tests``, Git-backed checks run and status may become
    ``verified`` when all checks pass.
    """
    errors: list[str] = []
    warnings: list[str] = []
    post_test_violations: list[str] = []

    impl = str(verification.get("implementation_sha", "")).strip()
    tests = str(verification.get("tests_commit_sha", "")).strip()
    final_head = str(verification.get("final_head_sha", "")).strip()
    remote_head = str(verification.get("remote_head_sha", "")).strip()
    validator_sha = str(verification.get("validator_commit_sha", "")).strip()

    for field_name, value in (
        ("base_sha", verification.get("base_sha")),
        ("implementation_sha", impl or None),
        ("tests_commit_sha", tests or None),
        ("final_head_sha", final_head or None),
        ("remote_head_sha", remote_head or None),
        ("validator_commit_sha", validator_sha or None),
    ):
        _validate_sha_field(field_name, value, errors, rel)

    test_exit = str(verification.get("test_exit_code", "")).strip()
    if test_exit and test_exit != "0":
        errors.append(f"{rel}: test_exit_code must be 0 (got {test_exit!r})")
    validator_exit = str(verification.get("validator_exit_code", "")).strip()
    if validator_exit and validator_exit != "0":
        errors.append(f"{rel}: validator_exit_code must be 0 (got {validator_exit!r})")

    if impl and tests and impl.lower() != tests.lower():
        errors.append(
            f"{rel}: tests_commit_sha ({tests}) must equal implementation_sha ({impl})"
        )

    if final_head and remote_head and final_head.lower() != remote_head.lower():
        errors.append(
            f"{rel}: final_head_sha ({final_head}) must equal remote_head_sha ({remote_head})"
        )

    if tests and final_head and tests.lower() == final_head.lower():
        # Allowed when no post-test commits; post_test_files should be empty/none.
        pass
    elif tests and final_head and tests.lower() != final_head.lower():
        policy = str(verification.get("post_test_diff_policy", "")).strip()
        if not policy:
            warnings.append(
                f"{rel}: tests_commit_sha differs from final_head_sha; "
                "post_test_diff_policy should document the allowlist"
            )

    git_context = bool(actual_head_sha or changed_files_after_tests is not None)
    if actual_head_sha:
        if final_head and actual_head_sha.lower() != final_head.lower():
            errors.append(
                f"{rel}: final_head_sha ({final_head}) does not match actual HEAD ({actual_head_sha})"
            )
        if remote_head and actual_head_sha.lower() != remote_head.lower():
            errors.append(
                f"{rel}: remote_head_sha ({remote_head}) does not match actual HEAD ({actual_head_sha}); "
                "git equality was not verified"
            )

    if changed_files_after_tests is not None:
        allowed, violations = classify_post_test_files(changed_files_after_tests)
        post_test_violations = violations
        if violations:
            errors.append(
                f"{rel}: post-test changes outside allowlist: {', '.join(violations)}"
            )
        recorded = str(verification.get("post_test_files", "")).strip()
        if recorded and recorded.lower() not in {"none", "n/a", "(none)"}:
            recorded_set = {p.strip() for p in recorded.split(",") if p.strip()}
            allowed_set = set(allowed)
            if recorded_set != allowed_set and recorded_set - allowed_set:
                warnings.append(
                    f"{rel}: post_test_files in handoff does not match supplied changed-file list"
                )

    if errors:
        return ValidationResult(status="failed", errors=errors, warnings=warnings, post_test_violations=post_test_violations)

    if git_context:
        return ValidationResult(status="verified", errors=[], warnings=warnings, post_test_violations=post_test_violations)

    warnings.append(
        f"{rel}: Git-backed checks not run (supply actual_head_sha and changed_files_after_tests via "
        "scripts/verify_repository_verification.py for full verification)"
    )
    return ValidationResult(status="structurally_valid", errors=[], warnings=warnings, post_test_violations=post_test_violations)


def validate_handoff_verification_block(rel: str, text: str, errors: list[str]) -> None:
    """Structural v2 handoff verification (offline, no network, no git)."""
    marker = "**Handoff Protocol:** v2"
    if marker not in text:
        return
    if "## Repository Verification" not in text:
        errors.append(f"{rel}: v2 handoff missing section ## Repository Verification")
        return
    for field in REQUIRED_VERIFICATION_FIELDS_V2:
        if field not in text:
            errors.append(f"{rel}: v2 handoff missing verification field {field.rstrip(':')}")
    verification = parse_verification_block(text)
    result = validate_repository_verification(verification, rel=rel)
    errors.extend(result.errors)
    for warning in result.warnings:
        if "Git-backed checks not run" not in warning:
            pass  # structural warnings only surfaced in CLI mode


def git_is_ancestor(ancestor: str, descendant: str, repo_root: str | None = None) -> bool | None:
    """Return True/False if ancestor relationship holds, None if git unavailable."""
    import subprocess
    from pathlib import Path

    cwd = Path(repo_root) if repo_root else None
    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
    except (OSError, FileNotFoundError):
        return None
    return None


def git_changed_files_since(base_sha: str, head_sha: str, repo_root: str | None = None) -> list[str] | None:
    import subprocess
    from pathlib import Path

    cwd = Path(repo_root) if repo_root else None
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except (OSError, FileNotFoundError):
        return None