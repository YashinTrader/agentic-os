"""Minimal environment construction for real-agent adapters — allowlist only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Platform-safe defaults; adapter config may extend via environment_allowlist.
DEFAULT_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
    }
)

DEFAULT_ENV_DENYLIST = frozenset(
    {
        "AGENTIC_OS_HUMAN_APPROVAL_KEY",
        "AGENTIC_OS_REVIEWER_APPROVAL_KEY",
        "AGENTIC_OS_HUMAN_APPROVAL_KEY_ID",
        "AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID",
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "STRIPE_SECRET_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "SMTP_PASSWORD",
        "MAILGUN_API_KEY",
    }
)


def merge_allowlists(
    adapter_allowlist: list[str] | tuple[str, ...] | None,
    *,
    extra: frozenset[str] | None = None,
) -> frozenset[str]:
    names = set(DEFAULT_ENV_ALLOWLIST)
    if extra:
        names.update(extra)
    for item in adapter_allowlist or []:
        name = str(item).strip()
        if name:
            names.add(name)
    return frozenset(names)


def default_codex_home(parent_env: dict[str, str] | os._Environ[str] | None = None) -> Path:
    """Resolve Codex config directory without reading secrets."""
    source = dict(parent_env if parent_env is not None else os.environ)
    explicit = str(source.get("CODEX_HOME", "")).strip()
    if explicit:
        return Path(explicit)
    profile = str(source.get("USERPROFILE") or source.get("HOME") or "").strip()
    return Path(profile) / ".codex" if profile else Path.home() / ".codex"


def codex_authentication_available(
    parent_env: dict[str, str] | os._Environ[str] | None = None,
) -> tuple[bool, str]:
    """Return (available, source_label). Never exposes secret values."""
    source = dict(parent_env if parent_env is not None else os.environ)
    if str(source.get("OPENAI_API_KEY", "")).strip():
        return True, "OPENAI_API_KEY"
    auth_path = default_codex_home(source) / "auth.json"
    if not auth_path.is_file():
        return False, ""
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, ""
    if str(data.get("OPENAI_API_KEY", "")).strip():
        return True, "codex_auth_file"
    if data.get("tokens"):
        return True, "codex_chatgpt_session"
    if str(data.get("auth_mode", "")).strip().lower() in {"chatgpt", "oauth"}:
        return True, "codex_chatgpt_session"
    return False, ""


def augment_codex_cli_environment(
    filtered: dict[str, str],
    *,
    parent_env: dict[str, str] | os._Environ[str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Ensure CODEX_HOME is set when the CLI can use on-disk session auth."""
    source = dict(parent_env if parent_env is not None else os.environ)
    augmented = dict(filtered)
    names = list(augmented.keys())
    if "CODEX_HOME" not in augmented:
        codex_home = default_codex_home(source)
        if codex_home.is_dir():
            augmented["CODEX_HOME"] = str(codex_home)
            names.append("CODEX_HOME")
    return augmented, sorted(set(names))


def build_minimal_environment(
    parent_env: dict[str, str] | os._Environ[str] | None = None,
    *,
    allowlist: frozenset[str] | set[str] | None = None,
    denylist: frozenset[str] | set[str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Return (filtered_env, allowed_variable_names). Values are never logged by callers."""
    source = dict(parent_env if parent_env is not None else os.environ)
    allowed_names = frozenset(allowlist or DEFAULT_ENV_ALLOWLIST)
    denied = frozenset(denylist or DEFAULT_ENV_DENYLIST)

    filtered: dict[str, str] = {}
    emitted_names: list[str] = []
    for name in sorted(allowed_names):
        if name in denied:
            continue
        value = source.get(name)
        if value is not None and value != "":
            filtered[name] = value
            emitted_names.append(name)
    return filtered, emitted_names


def environment_preview(
    adapter: dict[str, Any],
    *,
    parent_env: dict[str, str] | os._Environ[str] | None = None,
) -> dict[str, Any]:
    """Serializable preview — variable names only, never values."""
    allow = merge_allowlists(adapter.get("environment_allowlist"))
    deny = frozenset(adapter.get("environment_denylist") or DEFAULT_ENV_DENYLIST)
    filtered, names = build_minimal_environment(parent_env, allowlist=allow, denylist=deny)
    auth_ok, auth_source = codex_authentication_available(parent_env)
    if auth_ok and auth_source != "OPENAI_API_KEY":
        filtered, names = augment_codex_cli_environment(filtered, parent_env=parent_env)
    blocked: list[str] = []
    if adapter.get("secrets_required") and not auth_ok:
        blocked.append(
            "Codex authentication unavailable: set OPENAI_API_KEY or run `codex login`"
        )
    return {
        "environment_variable_names": names,
        "environment_allowlist": sorted(allow),
        "environment_denylist": sorted(deny),
        "authentication_source": auth_source,
        "blocked_reasons": blocked,
    }


def redact_environment_for_log(env: dict[str, str]) -> dict[str, str]:
    """Replace values with placeholders for safe structured logging."""
    return {key: "<redacted>" for key in env}