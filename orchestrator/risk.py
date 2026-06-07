"""Deterministic risk and approval gate for orchestration plans."""

from __future__ import annotations

import re
from typing import Any

HUMAN_KEYWORDS = {
    "deploy",
    "deployment",
    "production",
    "prod",
    "secret",
    "secrets",
    "api key",
    "apikey",
    "credential",
    "password",
    "token",
    "merge to main",
    "merge main",
    "ci/cd",
    "pipeline",
    "paid api",
    "billing",
    "destructive",
    "delete",
    "drop table",
    "database migration",
    "permission model",
    "security model",
    "autonomous",
    "execute agent",
    "launch agent",
}

REVIEWER_KEYWORDS = {
    "adr",
    "registry",
    "validator",
    "dashboard",
    "protocol",
    "schema",
    "handoff",
    "orchestrator",
    "langgraph",
}

READ_ONLY_KEYWORDS = {
    "dry-run",
    "dry run",
    "read-only",
    "read only",
    "planning",
    "suggest",
    "summary",
    "summarize",
    "observe-only",
    "observe only",
    "metadata",
}


def _combined_text(task: dict[str, Any], state: dict[str, Any]) -> str:
    parts = [
        str(task.get("title", "")),
        str(task.get("objective", "")),
        str(task.get("context", "")),
        str(task.get("notes", "")),
        " ".join(str(x) for x in task.get("constraints", []) if x),
        " ".join(str(x) for x in task.get("outputs", []) if x),
        " ".join(str(x) for x in task.get("goals", []) if x),
        str(state.get("next_action", "")),
    ]
    return " ".join(parts).lower()


def evaluate_risk(task: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    text = _combined_text(task, state)
    risk_level = str(task.get("risk_level", state.get("risk_level", "medium"))).lower()
    requires_human_flag = bool(task.get("requires_human_approval"))

    for keyword in READ_ONLY_KEYWORDS:
        if keyword in text:
            return {
                "approval_required": False,
                "approval_level": "none",
                "approval_reason": f"Read-only/planning task ({keyword}) — no human approval required.",
            }

    for keyword in HUMAN_KEYWORDS:
        if keyword in text:
            return {
                "approval_required": True,
                "approval_level": "human",
                "approval_reason": f"High-risk indicator detected: '{keyword}'.",
            }

    if requires_human_flag or risk_level == "high":
        if re.search(r"\b(deploy|secret|merge|production|destructive|database)\b", text):
            return {
                "approval_required": True,
                "approval_level": "human",
                "approval_reason": "High risk_level or requires_human_approval with risky scope.",
            }

    for keyword in REVIEWER_KEYWORDS:
        if keyword in text:
            return {
                "approval_required": True,
                "approval_level": "reviewer",
                "approval_reason": f"Protocol/registry change — reviewer approval sufficient ('{keyword}').",
            }

    return {
        "approval_required": risk_level in {"medium", "high"},
        "approval_level": "reviewer" if risk_level != "low" else "none",
        "approval_reason": "Routine implementation — reviewer sign-off recommended." if risk_level != "low" else "Low-risk planning task.",
    }