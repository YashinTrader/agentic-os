"""Deterministic risk and approval gate for orchestration plans."""

from __future__ import annotations

from typing import Any

# Precedence: blocked > human > reviewer > none
# Read-only/dry-run wording must NOT override human-risk indicators.

HUMAN_KEYWORDS: tuple[str, ...] = (
    "production db",
    "github actions",
    "merge to main",
    "push to main",
    "external side effect",
    "remove files",
    "paid api",
    "api key",
    "rm -rf",
    "deployment",
    "destructive",
    "credential",
    "execute mcp",
    "launch agent",
    "send email",
    "production",
    "database",
    "secrets",
    "billing",
    "password",
    "secret",
    "deploy",
    "delete",
    "spend",
    "token",
    "ci/cd",
    "call api",
    "prod",
)

REVIEWER_KEYWORDS: tuple[str, ...] = (
    "orchestrator",
    "langgraph",
    "validator",
    "protocol",
    "registry",
    "handoff",
    "dashboard",
    "schema",
    "adr",
)

READ_ONLY_KEYWORDS: tuple[str, ...] = (
    "dry-run",
    "dry run",
    "read-only",
    "read only",
    "observe-only",
    "observe only",
    "planning",
    "summarize",
    "summary",
    "suggest",
    "metadata",
)

BLOCKED_KEYWORDS: tuple[str, ...] = (
    "do not execute",
    "do not proceed",
    "halt work",
    "stop work",
)


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


def _first_keyword_match(text: str, keywords: tuple[str, ...]) -> str | None:
    for keyword in sorted(keywords, key=len, reverse=True):
        if keyword in text:
            return keyword
    return None


def evaluate_risk(task: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    text = _combined_text(task, state)
    risk_level = str(task.get("risk_level", state.get("risk_level", "medium"))).lower()
    requires_human_flag = bool(task.get("requires_human_approval"))
    status = str(task.get("status", "")).lower()

    # 1. blocked
    if status == "blocked":
        return {
            "approval_required": True,
            "approval_level": "blocked",
            "approval_reason": "Task status is blocked — dispatch must not proceed.",
        }
    blocked_kw = _first_keyword_match(text, BLOCKED_KEYWORDS)
    if blocked_kw:
        return {
            "approval_required": True,
            "approval_level": "blocked",
            "approval_reason": f"Blocked indicator detected: '{blocked_kw}'.",
        }

    # 2. human — flag and high risk are authoritative; keywords beat read-only wording
    if requires_human_flag:
        return {
            "approval_required": True,
            "approval_level": "human",
            "approval_reason": "requires_human_approval is true — human approval required.",
        }

    if risk_level == "high":
        return {
            "approval_required": True,
            "approval_level": "human",
            "approval_reason": "risk_level is high — human approval required.",
        }

    human_kw = _first_keyword_match(text, HUMAN_KEYWORDS)
    if human_kw:
        return {
            "approval_required": True,
            "approval_level": "human",
            "approval_reason": f"High-risk indicator detected: '{human_kw}'.",
        }

    # 3. reviewer
    reviewer_kw = _first_keyword_match(text, REVIEWER_KEYWORDS)
    if reviewer_kw:
        return {
            "approval_required": True,
            "approval_level": "reviewer",
            "approval_reason": (
                f"Protocol/registry change — reviewer approval sufficient ('{reviewer_kw}')."
            ),
        }

    if risk_level == "medium":
        return {
            "approval_required": True,
            "approval_level": "reviewer",
            "approval_reason": "Medium risk_level — reviewer sign-off recommended.",
        }

    # 4. none — read-only/planning tasks with no higher indicators
    read_only_kw = _first_keyword_match(text, READ_ONLY_KEYWORDS)
    if read_only_kw:
        return {
            "approval_required": False,
            "approval_level": "none",
            "approval_reason": f"Read-only/planning task ('{read_only_kw}') — no approval required.",
        }

    return {
        "approval_required": False,
        "approval_level": "none",
        "approval_reason": "Low-risk planning task.",
    }