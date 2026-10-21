"""Per-assignment MCP isolation for agent launches.

Policy (Phase 3.9.5):
- Task/assignment field ``required_mcp_servers`` is optional (default []).
- Default empty list means the launch must not connect to any optional MCP
  servers from the operator's user-level CLI config.
- Failure of an unlisted MCP must be impossible by construction.
- Failure of a *required* MCP is a real ``blocked_external`` (not silent).

Codex CLI flags used (per-invocation only; no user config mutation):
- Always inject ``-c mcp_servers={}`` so nested user tables cannot survive
  as a merge residue when the runtime supports table replacement.
- Always inject ``--ignore-user-config`` so ``$CODEX_HOME/config.toml`` MCP
  server tables are not loaded. Auth still uses ``CODEX_HOME`` (Codex CLI
  contract). Required servers, when listed, are rehydrated from a *read-only*
  snapshot of the operator config into additional ``-c`` keys when their
  definitions are simple enough; otherwise the launch records a blocked
  reason that the required server cannot be isolated safely.

Grok Build CLI: no per-invocation MCP allowlist flag was discoverable on the
installed CLI surface; see ``GROK_MCP_ISOLATION_GAP`` and launcher docs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

# Codex CLI config override flag (repeatable key=value).
CODEX_CONFIG_FLAG = "-c"
CODEX_IGNORE_USER_CONFIG_FLAG = "--ignore-user-config"

# Empty MCP table override — disable all servers declared in user config.
CODEX_EMPTY_MCP_SERVERS_OVERRIDE = "mcp_servers={}"

# Documented Grok gap (truthful; do not invent unsupported flags).
GROK_MCP_ISOLATION_GAP = (
    "Grok Build CLI (grok) has no documented per-invocation MCP allowlist or "
    "config-override flag equivalent to Codex `-c mcp_servers={}` / "
    "`--ignore-user-config`. MCP isolation for composer/Grok launches is a "
    "known gap: required_mcp_servers is recorded on the plan for policy "
    "parity, but the process argv cannot yet enforce zero-MCP isolation."
)

_MCP_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Patterns that indicate a *required* MCP failed (OAuth/auth/transport).
_REQUIRED_MCP_FAILURE_PATTERNS = (
    re.compile(r"AuthRequired", re.I),
    re.compile(r"invalid_token", re.I),
    re.compile(r"oauth", re.I),
    re.compile(r"mcp[_\s.-]?server", re.I),
    re.compile(r"rmcp::transport", re.I),
    re.compile(r"failed to (?:start|connect|initialize).{0,40}mcp", re.I),
    re.compile(r"www-authenticate", re.I),
)


def normalize_required_mcp_servers(value: Any) -> list[str]:
    """Return a de-duplicated, ordered list of MCP server names (default [])."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise TypeError(
            f"required_mcp_servers must be a list of strings, got {type(value).__name__}"
        )
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        name = str(raw).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def validate_required_mcp_servers(value: Any) -> list[str]:
    """Return schema validation errors for required_mcp_servers (empty = ok)."""
    errors: list[str] = []
    if value is None:
        return errors
    if not isinstance(value, (list, tuple)):
        return ["required_mcp_servers must be a list"]
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"required_mcp_servers[{idx}] must be a string")
            continue
        name = item.strip()
        if not name:
            errors.append(f"required_mcp_servers[{idx}] must be non-empty")
        elif not _MCP_SERVER_NAME_RE.match(name):
            errors.append(
                f"required_mcp_servers[{idx}] invalid name {name!r} "
                "(expected [A-Za-z0-9][A-Za-z0-9._-]{0,63})"
            )
    # Detect duplicates after strip
    try:
        normalized = normalize_required_mcp_servers(value)
    except TypeError as exc:
        return [str(exc)]
    stripped = [str(x).strip() for x in value if str(x).strip()]
    if len(stripped) != len(normalized):
        errors.append("required_mcp_servers must not contain duplicates")
    return errors


def extract_required_mcp_servers(payload: dict[str, Any] | None) -> list[str]:
    """Pull required_mcp_servers from task YAML or assignment payload.

    Resolution order:
    1. top-level ``required_mcp_servers``
    2. ``execution.required_mcp_servers``
    3. default []
    """
    if not isinstance(payload, dict):
        return []
    if "required_mcp_servers" in payload:
        return normalize_required_mcp_servers(payload.get("required_mcp_servers"))
    execution = payload.get("execution")
    if isinstance(execution, dict) and "required_mcp_servers" in execution:
        return normalize_required_mcp_servers(execution.get("required_mcp_servers"))
    return []


def build_codex_mcp_isolation_flags(
    required_mcp_servers: Sequence[str] | None = None,
    *,
    user_mcp_servers: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Build Codex argv fragments that isolate MCP servers for one invocation.

    Returns:
        (flags, blocked_reasons, evidence)
        flags are inserted after the ``exec`` subcommand and before other options.
    """
    required = normalize_required_mcp_servers(list(required_mcp_servers or []))
    blocked: list[str] = []
    evidence: dict[str, Any] = {
        "required_mcp_servers": list(required),
        "isolation_mode": "codex_cli_overrides",
        "flags": [],
        "codex_flags_documented": [
            f"{CODEX_CONFIG_FLAG} {CODEX_EMPTY_MCP_SERVERS_OVERRIDE}",
            CODEX_IGNORE_USER_CONFIG_FLAG,
        ],
        "rehydrated_servers": [],
        "skipped_rehydrate": [],
    }

    # Base isolation: never load user config.toml MCP tables; clear table.
    flags: list[str] = [
        CODEX_IGNORE_USER_CONFIG_FLAG,
        CODEX_CONFIG_FLAG,
        CODEX_EMPTY_MCP_SERVERS_OVERRIDE,
    ]

    if not required:
        evidence["flags"] = list(flags)
        evidence["policy"] = "zero_optional_mcp_connections"
        return flags, blocked, evidence

    # Required servers: rehydrate simple definitions from a read-only snapshot.
    source = user_mcp_servers or {}
    rehydrated: list[str] = []
    for name in required:
        if name not in source:
            blocked.append(
                f"required MCP server {name!r} is not defined in operator Codex "
                "config; cannot isolate/rehydrate for launch"
            )
            evidence["skipped_rehydrate"].append({"name": name, "reason": "missing_in_user_config"})
            continue
        definition = source[name]
        override = _format_mcp_server_override(name, definition)
        if override is None:
            blocked.append(
                f"required MCP server {name!r} has a config shape that cannot be "
                "safely rehydrated via Codex -c overrides"
            )
            evidence["skipped_rehydrate"].append({"name": name, "reason": "unsupported_shape"})
            continue
        flags.extend([CODEX_CONFIG_FLAG, override])
        rehydrated.append(name)

    evidence["flags"] = list(flags)
    evidence["rehydrated_servers"] = rehydrated
    evidence["policy"] = "required_mcp_servers_only"
    return flags, blocked, evidence


def _format_mcp_server_override(name: str, definition: Any) -> str | None:
    """Serialize a simple MCP server table to a Codex ``-c`` TOML override.

    Supports the common cases:
    - ``{command="…", args=[…]}``
    - ``{url="…"}``
    Nested env maps and tool approval tables are not rehydrated (returns None).
    """
    if not isinstance(definition, dict):
        return None
    # Reject nested tables we cannot faithfully rehydrate.
    for key, value in definition.items():
        if isinstance(value, dict):
            return None
        if key not in {
            "command",
            "args",
            "url",
            "startup_timeout_sec",
            "startup_timeout_ms",
            "tool_timeout_sec",
            "enabled",
        }:
            # Unknown keys: be conservative.
            if isinstance(value, (list, dict)):
                return None

    parts: list[str] = []
    if "command" in definition:
        parts.append(f"command={_toml_string(definition['command'])}")
    if "args" in definition:
        args = definition["args"]
        if not isinstance(args, list) or not all(isinstance(a, (str, int, float, bool)) for a in args):
            return None
        rendered = ", ".join(_toml_literal(a) for a in args)
        parts.append(f"args=[{rendered}]")
    if "url" in definition:
        parts.append(f"url={_toml_string(definition['url'])}")
    for numeric_key in ("startup_timeout_sec", "startup_timeout_ms", "tool_timeout_sec"):
        if numeric_key in definition:
            parts.append(f"{numeric_key}={_toml_literal(definition[numeric_key])}")
    if "enabled" in definition:
        parts.append(f"enabled={_toml_literal(definition['enabled'])}")
    if not parts:
        return None
    # dotted path assignment for one server table body.
    # Codex -c uses dotted paths: mcp_servers.name={…}
    return f"mcp_servers.{name}={{{', '.join(parts)}}}"


def _toml_string(value: Any) -> str:
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return _toml_string(value)


def load_user_mcp_servers(codex_home: Path | None = None) -> dict[str, Any]:
    """Read-only load of ``[mcp_servers.*]`` from operator Codex config.

    Never writes. Returns {} if missing/unreadable.
    """
    home = codex_home or Path.home() / ".codex"
    config_path = Path(home) / "config.toml"
    if not config_path.is_file():
        return {}
    try:
        try:
            import tomllib
        except ImportError:  # pragma: no cover - py<3.11
            import tomli as tomllib  # type: ignore
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    servers = data.get("mcp_servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    return {str(k): v for k, v in servers.items() if isinstance(v, dict)}


def build_grok_mcp_isolation_note(
    required_mcp_servers: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Record Grok isolation intent + documented gap (no argv mutation)."""
    required = normalize_required_mcp_servers(list(required_mcp_servers or []))
    return {
        "required_mcp_servers": required,
        "isolation_mode": "unsupported",
        "gap": GROK_MCP_ISOLATION_GAP,
        "flags": [],
        "policy": "zero_optional_mcp_connections" if not required else "required_mcp_servers_only",
    }


def classify_required_mcp_failure(
    *,
    required_mcp_servers: Sequence[str],
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
) -> dict[str, Any] | None:
    """If a required MCP failure is evident, return classification details.

    Returns None when no required-MCP failure is detected.
    """
    required = normalize_required_mcp_servers(list(required_mcp_servers or []))
    if not required:
        return None
    blob = f"{stdout}\n{stderr}"
    if not blob.strip() and exit_code in (0, None):
        return None

    matched_patterns: list[str] = []
    for pattern in _REQUIRED_MCP_FAILURE_PATTERNS:
        if pattern.search(blob):
            matched_patterns.append(pattern.pattern)

    named = [name for name in required if re.search(re.escape(name), blob, re.I)]
    if not matched_patterns and not named:
        # Nonzero exit with required servers declared but no MCP-shaped signal:
        # do not force blocked_external (could be unrelated code failure).
        return None

    reason_bits = []
    if named:
        reason_bits.append(f"required MCP server(s) mentioned: {', '.join(named)}")
    if matched_patterns:
        reason_bits.append(f"mcp failure patterns: {', '.join(matched_patterns[:3])}")
    if exit_code not in (0, None):
        reason_bits.append(f"exit_code={exit_code}")
    return {
        "process_state": "blocked_external",
        "category": "blocked_external",
        "detail": "required MCP failure: " + "; ".join(reason_bits),
        "required_mcp_servers": required,
        "matched_servers": named,
        "retry_eligible": False,
    }


def simulate_unlisted_mcp_cannot_abort(
    *,
    required_mcp_servers: Sequence[str] | None,
    unlisted_server: str,
    unlisted_error: str,
) -> dict[str, Any]:
    """Simulated stale-token proof for unlisted MCP servers.

    By construction, isolation flags clear user MCP tables before launch, so an
    unlisted server's auth failure cannot appear as a launch-abort cause. This
    helper encodes that policy for unit tests without invoking the real CLI.
    """
    required = normalize_required_mcp_servers(list(required_mcp_servers or []))
    flags, blocked, evidence = build_codex_mcp_isolation_flags(required)
    unlisted = str(unlisted_server).strip()
    isolated_away = unlisted not in required
    return {
        "unlisted_server": unlisted,
        "unlisted_error": unlisted_error,
        "required_mcp_servers": required,
        "isolation_flags": flags,
        "isolation_blocked_reasons": blocked,
        "evidence": evidence,
        "unlisted_isolated_away": isolated_away,
        "can_abort_run": False if isolated_away and not blocked else bool(blocked),
        "proof": (
            f"unlisted MCP {unlisted!r} is not in required_mcp_servers={required!r}; "
            f"launch uses {flags!r} so its failure ({unlisted_error!r}) cannot abort the run"
        ),
    }
