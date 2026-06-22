"""Minimal environment construction for real-agent adapters — allowlist only."""

from __future__ import annotations

import os
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
    _, names = build_minimal_environment(parent_env, allowlist=allow, denylist=deny)
    blocked: list[str] = []
    if adapter.get("secrets_required") and "OPENAI_API_KEY" not in names:
        blocked.append(
            "Codex authentication variable OPENAI_API_KEY not present in filtered environment"
        )
    return {
        "environment_variable_names": names,
        "environment_allowlist": sorted(allow),
        "environment_denylist": sorted(deny),
        "blocked_reasons": blocked,
    }


def redact_environment_for_log(env: dict[str, str]) -> dict[str, str]:
    """Replace values with placeholders for safe structured logging."""
    return {key: "<redacted>" for key in env}