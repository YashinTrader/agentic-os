"""Repository verification helpers for Handoff Protocol v2.

Offline validation checks structure and recorded invariants from handoff text.
Git-backed checks (ancestor relationship, post-test diff, artifact cross-check,
validator-at-HEAD) run via CLI or when callers supply git context.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")

UNITTEST_ARTIFACT_REL = "runtime/unittest_last_run.txt"

# Explicit post-test allowlist — no broad directory prefixes.
POST_TEST_ALLOWLIST_EXACT = frozenset(
    {
        "handoffs/T-M1-32-LAUNCH-RESILIENCE__codex__to__claude.md",
        "handoffs/T-M1-25B-STATUS-READ-RACE__codex__to__claude.md",
        "handoffs/T-M1-28C-INVENTORY-TEST-ISOLATION__codex__to__claude.md",
        "handoffs/T-M1-27B-STALE-MOCK__codex__to__claude.md",
        "handoffs/T-M1-28B-PROCESS-INVENTORY__codex__to__claude.md",
        "handoffs/T-M1-27-CAPACITY-LEAK__codex__to__claude.md",
        "handoffs/T-M1-28-LEGACY-STATUS-TAKEOVER__codex__to__claude.md",
        "handoffs/T-M1-29-LAYER-TERMINATE-CRASH__codex__to__claude.md",
        "handoffs/T-M1-22-POSTDEPLOY-HYGIENE__codex__to__claude.md",
        "handoffs/T-M1-25-GRACEFUL-SUPERVISOR-STOP__codex__to__claude.md",
        "handoffs/T-M1-26-GROK-STREAMING-ACTIVITY__codex__to__claude.md",
        "handoffs/T-M1-21-REVIEW-ATTEMPT-EVIDENCE__codex__to__claude.md",
        "handoffs/T-M1-20-REVIEW-LEASE-RECOVERY__codex__to__claude.md",
        "handoffs/T-M1-19-R4-GATE-FIXES__codex__to__claude.md",
        "handoffs/T-M1-18-CONSUMER-FAIRNESS-STALE-CLAIMS__codex__to__claude.md",
        "handoffs/T-M1-17-CONFIG-ROOT__codex__to__claude.md",
        "handoffs/T-M1-16-WINDOWS-WRITE-CONTENTION__codex__to__claude.md",
        "handoffs/T-M1-15-PRELAUNCH-FAILURE-ISOLATION__codex__to__claude.md",
        "handoffs/T-M1-14-STRUCTURED-CLASSIFICATION__codex__to__claude.md",
        "handoffs/T-M1-INTEGRATION__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R2__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R3__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R4__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R5__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R6__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R7__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R8__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R9__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R10__claude__to__gabriel.md",
        "handoffs/T-M1-INTEGRATION-R11__claude__to__gabriel.md",
        "handoffs/T-M1-06-CLI-ENCODING__codex__to__claude.md",
        "handoffs/T-M1-02D-PAID-QUOTA-PROBE__codex__to__claude.md",
        "handoffs/T-M1-11-PROCESS-OWNERSHIP-FENCING__codex__to__claude.md",
        "handoffs/T-M1-05-PROVENANCE-DEPLOY-ROOT__codex__to__claude.md",
        "handoffs/T-M1-04B-THREE-DEADLINES__codex__to__claude.md",
        "handoffs/T-M1-08-WORK-LOCK__codex__to__claude.md",
        "handoffs/T-M1-04-CHILD-SUPERVISION__codex__to__claude.md",
          "runtime/unittest_last_run.txt",
          "handoffs/T-PHASE3-9-6B-ACTIVITY-DETECTION-FIX__codex__to__claude.md",
          "handoffs/T-PHASE3-9-6C-STREAM-VERDICT-SELECTION__codex__to__claude.md",
          "handoffs/T-M1-02-DEFERRED-REEVAL__codex__to__claude.md",
          "handoffs/T-M1-02C-BUILDER-CONDITION-RETRY__codex__to__claude.md",
          "handoffs/T-M1-02C-BUILDER-CONDITION-RETRY__grok__to__claude.md",
          "handoffs/T-PHASE3-7A-CODEX-CANARY-ACTIVATION__composer__to__claude.md",
        "docs/REVIEW_COMPOSER_PHASE_3_7A_SELF_REVIEW.md",
        "docs/PHASE_3_7A_BASELINE.md",
        "docs/PHASE_3_7A_CODEX_ACTIVATION_CANDIDATE.md",
        "docs/PHASE_3_7A_CANARY_PREFLIGHT.md",
        "docs/PHASE_3_7A_HUMAN_APPROVAL_REQUEST.md",
        "docs/PHASE_3_7A_LIVE_RUN_PROHIBITION.md",
        "docs/PHASE_3_7A_HARDENING_REPORT.md",
        "docs/PHASE_3_7A_REVIEW_PACKET.md",
        "tasks/active/T-PHASE3-7A-CODEX-CANARY-ACTIVATION.yaml",
        "handoffs/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX__composer__to__claude.md",
        "docs/REVIEW_COMPOSER_PHASE_3_7A_1_SELF_REVIEW.md",
        "tasks/active/T-PHASE3-7A-1-EXECUTOR-BYPASS-FIX.yaml",
        "decisions/ADR-0042-canary-only-dedicated-execution-route.md",
        "handoffs/T-PHASE3-7B-CODEX-CANARY-PREFLIGHT__composer__to__claude.md",
        "docs/REVIEW_COMPOSER_PHASE_3_7B_PREFLIGHT_SELF_REVIEW.md",
        "docs/PHASE_3_7B_BASELINE.md",
        "docs/PHASE_3_7B_HUMAN_APPROVAL_REQUEST.md",
        "tasks/active/T-PHASE3-7B-CODEX-CANARY-PREFLIGHT.yaml",
        "handoffs/T-PHASE3-7C-DASH-RUNS-INTEGRATION__composer__to__claude.md",
        "handoffs/T-PHASE3-7C-WORKER-LIFECYCLE-HARDENING__composer__to__claude.md",
        "handoffs/T-PHASE3-7C-PORCELAIN-PARSER-HARDENING__composer__to__claude.md",
        "handoffs/T-PHASE3-7C-DASH-RUN-VISIBILITY__composer__to__claude.md",
        "handoffs/T-PHASE3-8-COMPOSER-INTEGRATION-DESIGN__composer__to__claude.md",
        "handoffs/T-PHASE3-8B-ASSIGNMENT-LOOP-ACTIVATION__composer__to__claude.md",
        "handoffs/T-PHASE3-7C-SAFETY-SCANNER-GET-FORM__composer__to__claude.md",
        "handoffs/T-PHASE3-8B-REVIEWER-RESOLUTION__composer__to__claude.md",
        "handoffs/T-PHASE3-9-AGENT-WAKE-POKE__composer__to__claude.md",
        "handoffs/T-PHASE3-9-1-PHYSICAL-AGENT-LAUNCHER__composer__to__claude.md",
        "handoffs/T-PHASE3-9-5-AGENT-MCP-ISOLATION__composer__to__claude.md",
        "docs/RUN_TESTS_BOOTSTRAP_BLOCKER.md",
        "tasks/active/T-FIRST-AUTONOMOUS-CODEX-BUILD.yaml",
        "tasks/active/T-PHASE3-8B-ASSIGNMENT-LOOP-ACTIVATION.yaml",
        "tasks/active/T-PHASE3-8B-DOGFOOD.yaml",
        "tasks/active/T-PHASE3-7C-SAFETY-SCANNER-GET-FORM.yaml",
    }
)

POST_TEST_ALLOWLIST_PREFIXES: tuple[str, ...] = ()

POST_TEST_FORBIDDEN_PREFIXES = (
    "decisions/",
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

DEFAULT_VALIDATOR_TIMEOUT_SECONDS = 120.0


@dataclass
class ValidationResult:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    post_test_violations: list[str] = field(default_factory=list)
    artifact_status: str = ""
    git_ancestry_status: str = ""
    post_test_diff_status: str = ""
    validator_status: str = ""
    validator_exit_code: int | None = None


@dataclass
class ValidatorRunResult:
    exit_code: int
    stdout: str
    stderr: str
    error: str = ""


def repository_identity(root: Path | str) -> str:
    """Identity requires both complete root history and an exact configured origin."""
    root = Path(root).resolve()
    seen = set()
    expected_roots = None
    while root not in seen:
        seen.add(root)
        def git(*args):
            return subprocess.run(["git", *args], cwd=root, capture_output=True,
                                  text=True, check=True).stdout.strip()
        roots = sorted(git("rev-list", "--max-parents=0", "HEAD").splitlines())
        if expected_roots is not None and roots != expected_roots:
            raise ValueError("Local origin history identity mismatch")
        expected_roots = roots
        remotes = git("remote").splitlines()
        name = "canonical" if "canonical" in remotes else "origin"
        remote = git("config", "--get", f"remote.{name}.url")
        if not roots or not remote:
            raise ValueError("Repository identity requires root history and origin URL")
        local = Path(remote)
        if not local.is_absolute():
            local = root / local
        if local.is_dir():
            root = local.resolve()
            continue
        return json.dumps({"roots": roots, "origin": remote}, sort_keys=True)
    raise ValueError("Cyclic local repository origins")


TEST_EVIDENCE_FIELDS = (
    "tests_commit_sha", "test_count", "test_exit_code", "known_exempt_failures",
    "raw_output_sha256", "repo_identity", "dependency_install",
    "dependency_install_reason", "artifact_origin_path", "hostname",
    "python_version", "command_line", "timestamp", "python",
)


def test_evidence_from_artifact(artifact: dict[str, str]) -> dict[str, str]:
    evidence = {key: artifact.get(key, "") for key in TEST_EVIDENCE_FIELDS}
    evidence["tests_commit_sha"] = artifact.get("commit_full", "")
    evidence["test_exit_code"] = artifact.get("exit_code", "")
    return evidence


def evidence_block_hash(evidence: dict[str, Any] | str) -> str:
    """SHA-256 of UTF-8 compact, sorted JSON with fixed string-valued keys.

    Missing fields serialize as empty strings; whitespace around field values is
    insignificant. Commit-time closeout fields never participate in this seal.
    """
    if isinstance(evidence, str):
        section = evidence.split("## Repository Verification", 1)[1].split("\n## ", 1)[0]
        evidence = {key: verification_field_value(section, key) or "" for key in TEST_EVIDENCE_FIELDS}
    canonical = {key: str(evidence.get(key, "")).strip() for key in TEST_EVIDENCE_FIELDS}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_test_evidence(evidence: dict[str, str]) -> str:
    return "### Test Evidence\n\n" + "\n".join(
        f"{key}: {evidence.get(key, '')}" for key in TEST_EVIDENCE_FIELDS
    ) + "\n"


def failure_ids(output: str) -> list[str]:
    return [value.rstrip("\r") for value in re.findall(r"^(?:FAIL|ERROR): (.+)$", output, re.MULTILINE)]


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
    lines: list[str] = []
    for line in section.splitlines()[1:]:
        if line.startswith("## "):
            break
        lines.append(line)
    block = "\n".join(lines)
    out: dict[str, str] = {}
    for key in (
        *TEST_EVIDENCE_FIELDS,
        "repo_root",
        "branch",
        "base_sha",
        "implementation_sha",
        "final_head_sha",
        "remote_head_sha",
        "git_status_clean",
        "validator_commit_sha",
        "validator_exit_code",
        "post_test_diff_policy",
        "post_test_files",
        "working_copy_path",
        "final_head_ref",
        "artifact_parent_sha",
        "artifact_commit_sha",
    ):
        val = verification_field_value(block, f"{key}:")
        if val is not None:
            out[key] = val
    out["evidence_block_sha256"] = evidence_block_hash(out)
    if any(sum(line.strip().startswith(f"{key}:") for line in lines) > 1
           for key in TEST_EVIDENCE_FIELDS):
        out["duplicate_test_evidence"] = "true"
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


def parse_unittest_last_run(text: str) -> dict[str, str] | None:
    """Parse runtime/unittest_last_run.txt into a field dict."""
    if not text.strip():
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("--- "):
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    required = ("commit_full", "test_count", "exit_code", "repo_root")
    if not all(k in fields for k in required):
        return None
    return fields


def load_unittest_artifact(repo_root: Path | str) -> tuple[dict[str, str] | None, bool]:
    path = Path(repo_root) / UNITTEST_ARTIFACT_REL
    if not path.exists():
        return None, False
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return None, True
    fields = parse_unittest_last_run(text)
    if fields is not None:
        raw_output = raw.partition(b"--- raw output ---\n")[2]
        output = raw_output.decode("utf-8", errors="replace")
        fields["computed_output_sha256"] = hashlib.sha256(raw_output).hexdigest()
        for key in ("dependency_install", "dependency_install_reason"):
            match_metadata = re.search(rf"^{key}: ([^\n]*)$", output, re.MULTILINE)
            fields[f"computed_{key}"] = match_metadata.group(1) if match_metadata else ""
        ids = failure_ids(output)
        fields["computed_failures"] = json.dumps(ids)
        failed = re.search(r"^FAILED \(([^\n]+)\)", output, re.MULTILINE)
        counts = re.findall(r"(?:failures|errors)=(\d+)", failed.group(1)) if failed else []
        if failed and counts and sum(map(int, counts)) == len(ids):
            fields["computed_result"] = "failed"
        elif re.search(r"^OK(?: \([^\n]*\))?\s*$", output, re.MULTILINE) and not ids and not failed:
            fields["computed_result"] = "passed"
        else:
            fields["computed_result"] = "invalid"
        match = re.search(r"^Ran (\d+) tests? in ", output, re.MULTILINE)
        fields["computed_test_count"] = match.group(1) if match else ""
    return fields, True


def validate_test_artifact(
    artifact: dict[str, str] | None,
    *,
    verification: dict[str, Any],
    actual_head_sha: str | None,
    artifact_exists: bool,
    rel: str = "handoff",
    is_ancestor: Any | None = None,
) -> tuple[list[str], str]:
    """Cross-check unittest artifact against handoff verification block."""
    errors: list[str] = []
    if not artifact_exists:
        errors.append(f"{rel}: test artifact missing")
        return errors, "missing"

    if artifact is None:
        errors.append(f"{rel}: test artifact malformed")
        return errors, "malformed"

    if verification.get("duplicate_test_evidence"):
        errors.append(f"{rel}: duplicate test evidence field")
    for key in TEST_EVIDENCE_FIELDS:
        artifact_key = {"tests_commit_sha": "commit_full", "test_exit_code": "exit_code"}.get(key, key)
        if key not in verification or artifact_key not in artifact:
            errors.append(f"{rel}: missing test evidence field {key}")

    impl = str(verification.get("implementation_sha", "")).strip()
    tests = str(verification.get("tests_commit_sha", "")).strip()
    handoff_count = str(verification.get("test_count", "")).strip()
    handoff_exit = str(verification.get("test_exit_code", "")).strip()

    commit_full = artifact.get("commit_full", "")
    if not _SHA40_RE.match(commit_full):
        errors.append(f"{rel}: test artifact malformed")
        return errors, "malformed"

    if tests and commit_full.lower() != tests.lower():
        errors.append(f"{rel}: artifact commit does not match tests_commit_sha")

    if impl and tests and commit_full.lower() != impl.lower():
        errors.append(f"{rel}: artifact commit does not match tests_commit_sha")

    if handoff_count and artifact.get("test_count") != handoff_count:
        errors.append(f"{rel}: artifact test count mismatch")

    artifact_exit = artifact.get("exit_code", "")
    if handoff_exit and artifact_exit != handoff_exit:
        errors.append(f"{rel}: artifact exit code mismatch")
    try:
        exemptions = json.loads(str(verification.get("known_exempt_failures", "[]")))
        failures = json.loads(artifact.get("computed_failures", "[]"))
        if not isinstance(exemptions, list) or not all(isinstance(x, str) for x in exemptions):
            raise ValueError("exemptions must be a list of test ids")
        if artifact_exit != "0" and (not failures or any(x not in exemptions for x in failures)):
            errors.append(f"{rel}: unlisted test failure or non-test error")
        if artifact_exit == "0" and failures:
            errors.append(f"{rel}: failures conflict with zero exit code")
        int(artifact_exit)
    except (ValueError, TypeError):
        errors.append(f"{rel}: invalid exit code or known_exempt_failures")

    for key in ("dependency_install", "dependency_install_reason"):
        if key in artifact or artifact.get(f"computed_{key}"):
            if artifact.get(key, "") != artifact.get(f"computed_{key}", ""):
                errors.append(f"{rel}: artifact {key} mismatch with hashed output")
    expected_result = "passed" if artifact_exit == "0" else "failed"
    if artifact.get("computed_result") != expected_result:
        errors.append(f"{rel}: raw test summary conflicts with exit code or failures")
    expected_identity = verification.get("expected_repo_identity")
    if not expected_identity or artifact.get("repo_identity") != expected_identity:
        errors.append(f"{rel}: artifact repository identity mismatch")
    for key in ("artifact_origin_path", "hostname", "python_version", "command_line"):
        if not artifact.get(key):
            errors.append(f"{rel}: artifact missing {key}")
    if artifact.get("artifact_origin_path") != artifact.get("repo_root"):
        errors.append(f"{rel}: artifact origin path mismatch")
    for recorded, computed in (("raw_output_sha256", "computed_output_sha256"),
                               ("test_count", "computed_test_count")):
        if not artifact.get(computed) or artifact.get(recorded) != artifact.get(computed):
            errors.append(f"{rel}: artifact {recorded} mismatch")
    if artifact.get("evidence_block_sha256") != evidence_block_hash(verification):
        errors.append(f"{rel}: handoff evidence block hash mismatch")
    if artifact.get("evidence_block_sha256") != evidence_block_hash(test_evidence_from_artifact(artifact)):
        errors.append(f"{rel}: artifact evidence block hash mismatch")

    if not tests or not _SHA40_RE.fullmatch(tests):
        errors.append(f"{rel}: invalid tests_commit_sha")
    if not actual_head_sha or is_ancestor is None:
        errors.append(f"{rel}: artifact reachability was not verified")
    if actual_head_sha and is_ancestor is not None:
        ancestor = is_ancestor(commit_full, actual_head_sha)
        if ancestor is False:
            errors.append(f"{rel}: artifact commit not reachable from HEAD")
        elif ancestor is None:
            errors.append(f"{rel}: artifact commit not reachable from HEAD")

    if errors:
        return errors, "failed"
    return [], "verified"


def run_validator_at_head(
    repo_root: Path | str,
    *,
    timeout_seconds: float = DEFAULT_VALIDATOR_TIMEOUT_SECONDS,
    executable: str | None = None,
) -> ValidatorRunResult:
    root = Path(repo_root)
    validator = root / "scripts" / "validate.py"
    if not validator.exists():
        return ValidatorRunResult(exit_code=-1, stdout="", stderr="", error="validator missing")
    py = executable or sys.executable
    try:
        proc = subprocess.run(
            [py, str(validator)],
            cwd=root,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout_seconds,
            check=False,
        )
        return ValidatorRunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return ValidatorRunResult(
            exit_code=-1,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error="validator timeout",
        )
    except OSError as exc:
        return ValidatorRunResult(exit_code=-1, stdout="", stderr="", error=str(exc))


def validate_validator_at_head(
    validator_result: ValidatorRunResult | None,
    *,
    verification: dict[str, Any],
    rel: str = "handoff",
) -> tuple[list[str], str, int | None]:
    errors: list[str] = []
    declared_exit = str(verification.get("validator_exit_code", "")).strip()

    if validator_result is None:
        errors.append(f"{rel}: validator missing")
        return errors, "missing", None

    if validator_result.error == "validator missing":
        errors.append(f"{rel}: validator missing")
        return errors, "missing", None

    if validator_result.error == "validator timeout":
        errors.append(f"{rel}: validator timeout")
        return errors, "failed", validator_result.exit_code

    if validator_result.exit_code != 0:
        errors.append(f"{rel}: Validator at HEAD: failed")
        return errors, "failed", validator_result.exit_code

    if declared_exit and declared_exit != "0":
        errors.append(f"{rel}: validator_exit_code must be 0 (got {declared_exit!r})")

    if declared_exit and str(validator_result.exit_code) != declared_exit:
        errors.append(f"{rel}: declared validator_exit_code conflicts with actual validator result")

    return errors, "passed", validator_result.exit_code


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
    test_artifact: dict[str, str] | None = None,
    artifact_exists: bool | None = None,
    artifact_is_ancestor: Any | None = None,
    validator_result: ValidatorRunResult | None = None,
    run_artifact_checks: bool = False,
    run_validator_checks: bool = False,
) -> ValidationResult:
    """Validate a parsed Repository Verification block."""
    errors: list[str] = []
    warnings: list[str] = []
    post_test_violations: list[str] = []
    artifact_status = ""
    git_ancestry_status = ""
    post_test_diff_status = ""
    validator_status = ""
    validator_exit: int | None = None

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
        try:
            int(test_exit)
            exemptions = json.loads(str(verification.get("known_exempt_failures", "[]")))
            if not isinstance(exemptions, list) or not exemptions or not all(isinstance(x, str) and x for x in exemptions):
                raise ValueError("missing failure exemptions")
        except (ValueError, TypeError):
            errors.append(f"{rel}: non-zero test_exit_code requires known_exempt_failures test ids")
    validator_exit_declared = str(verification.get("validator_exit_code", "")).strip()
    if validator_exit_declared and validator_exit_declared != "0":
        errors.append(f"{rel}: validator_exit_code must be 0 (got {validator_exit_declared!r})")

    if impl and tests and impl.lower() != tests.lower():
        errors.append(
            f"{rel}: tests_commit_sha ({tests}) must equal implementation_sha ({impl})"
        )

    if final_head and remote_head and final_head.lower() != remote_head.lower():
        errors.append(
            f"{rel}: final_head_sha ({final_head}) must equal remote_head_sha ({remote_head})"
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

    if tests and final_head and tests.lower() != final_head.lower():
        policy = str(verification.get("post_test_diff_policy", "")).strip()
        if not policy:
            warnings.append(
                f"{rel}: tests_commit_sha differs from final_head_sha; "
                "post_test_diff_policy should document the allowlist"
            )

    if changed_files_after_tests is not None:
        allowed, violations = classify_post_test_files(changed_files_after_tests)
        post_test_violations = violations
        if violations:
            for path in violations:
                errors.append(f"{rel}: prohibited post-test file change: {path}")
            post_test_diff_status = "failed"
        else:
            post_test_diff_status = "verified"
        recorded = str(verification.get("post_test_files", "")).strip()
        if recorded and recorded.lower() not in {"none", "n/a", "(none)"}:
            recorded_set = {p.strip() for p in recorded.split(",") if p.strip()}
            allowed_set = set(allowed)
            if recorded_set != allowed_set and recorded_set - allowed_set:
                warnings.append(
                    f"{rel}: post_test_files in handoff does not match supplied changed-file list"
                )
    elif git_context:
        post_test_diff_status = "verified"

    if run_artifact_checks:
        if validator_sha and actual_head_sha and artifact_is_ancestor is not None:
            if artifact_is_ancestor(validator_sha, actual_head_sha) is not True:
                errors.append(f"{rel}: validator_commit_sha not reachable from HEAD")
        exists = bool(artifact_exists)
        artifact_errors, artifact_status = validate_test_artifact(
            test_artifact,
            verification=verification,
            actual_head_sha=actual_head_sha,
            artifact_exists=exists,
            rel=rel,
            is_ancestor=artifact_is_ancestor,
        )
        errors.extend(artifact_errors)

    if run_validator_checks:
        validator_errors, validator_status, validator_exit = validate_validator_at_head(
            validator_result,
            verification=verification,
            rel=rel,
        )
        errors.extend(validator_errors)

    if tests and final_head and git_context and not errors:
        git_ancestry_status = "verified"

    if errors:
        return ValidationResult(
            status="failed",
            errors=errors,
            warnings=warnings,
            post_test_violations=post_test_violations,
            artifact_status=artifact_status,
            git_ancestry_status=git_ancestry_status,
            post_test_diff_status=post_test_diff_status,
            validator_status=validator_status,
            validator_exit_code=validator_exit,
        )

    if git_context and (run_artifact_checks or run_validator_checks):
        return ValidationResult(
            status="verified",
            errors=[],
            warnings=warnings,
            post_test_violations=post_test_violations,
            artifact_status=artifact_status or ("verified" if run_artifact_checks else ""),
            git_ancestry_status=git_ancestry_status or "verified",
            post_test_diff_status=post_test_diff_status or "verified",
            validator_status=validator_status or ("passed" if run_validator_checks else ""),
            validator_exit_code=validator_exit,
        )

    if git_context:
        return ValidationResult(
            status="verified",
            errors=[],
            warnings=warnings,
            post_test_violations=post_test_violations,
            git_ancestry_status="verified",
            post_test_diff_status=post_test_diff_status or "verified",
        )

    warnings.append(
        f"{rel}: Git-backed checks not run (supply actual_head_sha and changed_files_after_tests via "
        "scripts/verify_repository_verification.py for full verification)"
    )
    return ValidationResult(
        status="structurally_valid",
        errors=[],
        warnings=warnings,
        post_test_violations=post_test_violations,
    )


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


def git_is_ancestor(ancestor: str, descendant: str, repo_root: str | None = None) -> bool | None:
    """Return True/False if ancestor relationship holds, None if git unavailable."""
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


def resolve_head_for_verification(
    actual_head: str,
    final_recorded: str,
    repo_root: str,
) -> str:
    """Allow one tip commit ahead when only explicit allowlisted files changed."""
    if not final_recorded or actual_head.lower() == final_recorded.lower():
        return actual_head
    tip_delta = git_changed_files_since(final_recorded, actual_head, repo_root)
    if tip_delta is not None and tip_delta and all(is_post_test_allowlisted(p) for p in tip_delta):
        return final_recorded
    return actual_head
