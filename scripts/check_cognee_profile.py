#!/usr/bin/env python3
"""Dry-run validator for the Agentic OS local Cognee profile.

This script validates configuration shape only. It does not import Cognee,
connect to Ollama, create databases, or ingest repository data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = REPO_ROOT / "memory" / "cognee-local.env.example"

REQUIRED_KEYS = {
    "AGENTIC_OS_MEMORY_BACKEND",
    "AGENTIC_OS_MEMORY_PROFILE",
    "AGENTIC_OS_ENABLE_CLOUD_PROVIDERS",
    "AGENTIC_OS_INGESTION_ENABLED",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_ENDPOINT",
    "LLM_API_KEY",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "GRAPH_DATABASE_PROVIDER",
    "VECTOR_DB_PROVIDER",
    "DB_PROVIDER",
    "DB_NAME",
    "SYSTEM_ROOT_DIRECTORY",
    "DATA_ROOT_DIRECTORY",
}

LOCAL_LLM_PROVIDERS = {"ollama"}
LOCAL_EMBEDDING_PROVIDERS = {"fastembed", "ollama"}
CLOUD_PROVIDERS = {"openai", "anthropic", "gemini", "azure", "bedrock", "groq", "mistral"}


class ProfileError(ValueError):
    """Raised when the local Cognee profile is unsafe or incomplete."""


def parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ProfileError(f"{field} must be true or false")


def load_profile(path: Path) -> dict[str, str]:
    profile: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ProfileError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if not key:
            raise ProfileError(f"{path}:{line_number}: key must not be empty")
        profile[key] = value
    return profile


def validate_profile(profile: dict[str, str]) -> dict[str, Any]:
    missing = sorted(REQUIRED_KEYS - set(profile))
    if missing:
        raise ProfileError(f"missing required keys: {', '.join(missing)}")

    if profile["AGENTIC_OS_MEMORY_BACKEND"] != "cognee":
        raise ProfileError("AGENTIC_OS_MEMORY_BACKEND must be cognee")
    if profile["AGENTIC_OS_MEMORY_PROFILE"] != "local":
        raise ProfileError("AGENTIC_OS_MEMORY_PROFILE must be local")

    cloud_enabled = parse_bool(profile["AGENTIC_OS_ENABLE_CLOUD_PROVIDERS"], "AGENTIC_OS_ENABLE_CLOUD_PROVIDERS")
    if cloud_enabled:
        raise ProfileError("cloud providers must be disabled by default")

    ingestion_enabled = parse_bool(profile["AGENTIC_OS_INGESTION_ENABLED"], "AGENTIC_OS_INGESTION_ENABLED")
    if ingestion_enabled:
        raise ProfileError("ingestion must be disabled in the Phase 2.1 bootstrap profile")

    llm_provider = profile["LLM_PROVIDER"].lower()
    embedding_provider = profile["EMBEDDING_PROVIDER"].lower()
    if llm_provider not in LOCAL_LLM_PROVIDERS or llm_provider in CLOUD_PROVIDERS:
        raise ProfileError("LLM_PROVIDER must be a local provider")
    if embedding_provider not in LOCAL_EMBEDDING_PROVIDERS or embedding_provider in CLOUD_PROVIDERS:
        raise ProfileError("EMBEDDING_PROVIDER must be a local provider")

    endpoint = profile["LLM_ENDPOINT"]
    if not (endpoint.startswith("http://localhost:") or endpoint.startswith("http://127.0.0.1:")):
        raise ProfileError("LLM_ENDPOINT must point at localhost")

    try:
        dimensions = int(profile["EMBEDDING_DIMENSIONS"])
    except ValueError as exc:
        raise ProfileError("EMBEDDING_DIMENSIONS must be an integer") from exc
    if dimensions <= 0:
        raise ProfileError("EMBEDDING_DIMENSIONS must be positive")

    if profile["GRAPH_DATABASE_PROVIDER"] != "kuzu":
        raise ProfileError("GRAPH_DATABASE_PROVIDER must be kuzu")
    if profile["VECTOR_DB_PROVIDER"] != "lancedb":
        raise ProfileError("VECTOR_DB_PROVIDER must be lancedb")
    if profile["DB_PROVIDER"] != "sqlite":
        raise ProfileError("DB_PROVIDER must be sqlite")

    for key in ("SYSTEM_ROOT_DIRECTORY", "DATA_ROOT_DIRECTORY"):
        value = profile[key]
        if value.startswith(("http://", "https://", "s3://")):
            raise ProfileError(f"{key} must be a local filesystem path")

    return {
        "profile": profile["AGENTIC_OS_MEMORY_PROFILE"],
        "backend": profile["AGENTIC_OS_MEMORY_BACKEND"],
        "llm_provider": llm_provider,
        "llm_model": profile["LLM_MODEL"],
        "embedding_provider": embedding_provider,
        "embedding_model": profile["EMBEDDING_MODEL"],
        "embedding_dimensions": dimensions,
        "graph_provider": profile["GRAPH_DATABASE_PROVIDER"],
        "vector_provider": profile["VECTOR_DB_PROVIDER"],
        "db_provider": profile["DB_PROVIDER"],
        "cloud_providers_enabled": cloud_enabled,
        "ingestion_enabled": ingestion_enabled,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Validate the local Cognee profile without running ingestion.")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH), help="Path to a Cognee env profile.")
    p.add_argument("--json", action="store_true", help="Print validation summary as JSON.")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        summary = validate_profile(load_profile(Path(args.profile)))
    except OSError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 1
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print("Cognee local profile validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
