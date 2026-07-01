"""Execution route policy — canary-only adapters reject generic dispatch (fail-closed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ROUTE_GENERIC_DISPATCH = "generic_dispatch"
ROUTE_CODEX_CANARY = "codex_canary"
ROUTE_CODEX_LOCAL_BUILDER = "codex_local_builder"
ROUTE_PREVIEW_ONLY = "preview_only"

RECOGNIZED_EXECUTION_ROUTES = frozenset(
    {ROUTE_GENERIC_DISPATCH, ROUTE_CODEX_CANARY, ROUTE_CODEX_LOCAL_BUILDER, ROUTE_PREVIEW_ONLY}
)

DEDICATED_CANARY_RUNNER_REASON = (
    "Adapter requires its dedicated canary runner; generic dispatch execution is prohibited."
)

RouteStatus = Literal["allowed", "blocked", "dedicated_runner_required"]


@dataclass
class ExecutionRouteDecision:
    allowed: bool
    required_route: str | None
    status: RouteStatus
    reasons: list[str] = field(default_factory=list)


def adapter_requires_dedicated_runner(adapter: dict[str, Any]) -> bool:
    scope = str(adapter.get("execution_scope", ""))
    if scope in {"canary_only", "local_worktree"}:
        return True
    if adapter.get("dedicated_runner_required"):
        return True
    if adapter.get("phase3_7b_authorization_required"):
        return True
    if str(adapter.get("promotion_state", "")) == "activation_candidate":
        return True
    required = str(adapter.get("required_execution_route", "")).strip()
    return bool(required and required != ROUTE_GENERIC_DISPATCH)


def required_execution_route_for_adapter(adapter: dict[str, Any]) -> str | None:
    explicit = str(adapter.get("required_execution_route", "")).strip()
    if explicit:
        return explicit
    scope = str(adapter.get("execution_scope", ""))
    if adapter.get("id") == "codex-restricted":
        if scope == "local_worktree":
            return ROUTE_CODEX_LOCAL_BUILDER
        return ROUTE_CODEX_CANARY
    if adapter.get("execution_scope") == "canary_only":
        return ROUTE_CODEX_CANARY
    return None


def validate_adapter_route_policy(adapter: dict[str, Any]) -> list[str]:
    """Static adapter policy contradictions for validator/tests."""
    blockers: list[str] = []
    adapter_id = str(adapter.get("id", ""))
    scope = str(adapter.get("execution_scope", ""))
    required = str(adapter.get("required_execution_route", "")).strip()

    if scope == "canary_only":
        if not adapter.get("dedicated_runner_required"):
            blockers.append(f"{adapter_id}: canary_only requires dedicated_runner_required=true")
        if not required:
            blockers.append(f"{adapter_id}: canary_only requires required_execution_route")
        elif required not in RECOGNIZED_EXECUTION_ROUTES:
            blockers.append(f"{adapter_id}: unrecognized required_execution_route {required!r}")
        elif required == ROUTE_GENERIC_DISPATCH:
            blockers.append(f"{adapter_id}: canary_only cannot use generic_dispatch route")

    if scope == "local_worktree":
        if not adapter.get("dedicated_runner_required"):
            blockers.append(f"{adapter_id}: local_worktree requires dedicated_runner_required=true")
        if required != ROUTE_CODEX_LOCAL_BUILDER:
            blockers.append(f"{adapter_id}: local_worktree requires required_execution_route=codex_local_builder")
        if adapter.get("phase3_7b_authorization_required"):
            blockers.append(f"{adapter_id}: local_worktree must not require phase3_7b authorization")

    if adapter.get("phase3_7b_authorization_required") and scope not in {"canary_only"}:
        blockers.append(f"{adapter_id}: phase3_7b_authorization_required implies canary_only scope")

    if adapter.get("supports_execution") and scope == "canary_only":
        max_runs = int(adapter.get("maximum_runs", 0) or 0)
        if max_runs != 1:
            blockers.append(f"{adapter_id}: canary_only maximum_runs must equal 1")

    if adapter_id != "codex-restricted" and adapter.get("supports_execution"):
        if adapter_requires_dedicated_runner(adapter):
            blockers.append(f"{adapter_id}: only codex-restricted may be canary-capable with supports_execution")

    if adapter_id == "local-python-exec-test" and scope == "canary_only":
        blockers.append("local-python-exec-test cannot be canary_only")

    return blockers


def evaluate_execution_route(
    adapter: dict[str, Any],
    requested_route: str,
) -> ExecutionRouteDecision:
    """Pure route policy — no subprocess, secrets, or approval consumption."""
    if requested_route not in RECOGNIZED_EXECUTION_ROUTES:
        return ExecutionRouteDecision(
            allowed=False,
            required_route=None,
            status="blocked",
            reasons=[f"unrecognized execution route: {requested_route!r}"],
        )

    adapter_id = str(adapter.get("id", ""))
    required = required_execution_route_for_adapter(adapter)

    if requested_route == ROUTE_PREVIEW_ONLY:
        return ExecutionRouteDecision(
            allowed=True,
            required_route=required,
            status="allowed",
            reasons=[],
        )

    if requested_route == ROUTE_GENERIC_DISPATCH:
        if adapter_requires_dedicated_runner(adapter):
            return ExecutionRouteDecision(
                allowed=False,
                required_route=required or ROUTE_CODEX_CANARY,
                status="dedicated_runner_required",
                reasons=[DEDICATED_CANARY_RUNNER_REASON],
            )
        return ExecutionRouteDecision(
            allowed=True,
            required_route=None,
            status="allowed",
            reasons=[],
        )

    if requested_route == ROUTE_CODEX_CANARY:
        reasons: list[str] = []
        if adapter_id != "codex-restricted":
            reasons.append(f"route codex_canary is not valid for adapter {adapter_id!r}")
        if str(adapter.get("execution_scope", "")) != "canary_only":
            reasons.append("execution_scope must be canary_only for codex_canary route")
        if required and required != ROUTE_CODEX_CANARY:
            reasons.append(f"adapter required_execution_route must be codex_canary (got {required!r})")
        if reasons:
            return ExecutionRouteDecision(
                allowed=False,
                required_route=ROUTE_CODEX_CANARY,
                status="blocked",
                reasons=reasons,
            )
        return ExecutionRouteDecision(
            allowed=True,
            required_route=ROUTE_CODEX_CANARY,
            status="allowed",
            reasons=[],
        )

    if requested_route == ROUTE_CODEX_LOCAL_BUILDER:
        reasons_lb: list[str] = []
        if adapter_id != "codex-restricted":
            reasons_lb.append(f"route codex_local_builder is not valid for adapter {adapter_id!r}")
        if str(adapter.get("execution_scope", "")) != "local_worktree":
            reasons_lb.append("execution_scope must be local_worktree for codex_local_builder route")
        if required and required != ROUTE_CODEX_LOCAL_BUILDER:
            reasons_lb.append(
                f"adapter required_execution_route must be codex_local_builder (got {required!r})"
            )
        if reasons_lb:
            return ExecutionRouteDecision(
                allowed=False,
                required_route=ROUTE_CODEX_LOCAL_BUILDER,
                status="blocked",
                reasons=reasons_lb,
            )
        return ExecutionRouteDecision(
            allowed=True,
            required_route=ROUTE_CODEX_LOCAL_BUILDER,
            status="allowed",
            reasons=[],
        )

    return ExecutionRouteDecision(
        allowed=False,
        required_route=required,
        status="blocked",
        reasons=[f"execution route {requested_route!r} is blocked"],
    )