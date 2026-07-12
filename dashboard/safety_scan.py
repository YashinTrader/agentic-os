"""Read-only control scanner for the dashboard (Phase 3.4 / 3.8B).

Distinguishes:
- GET-form submit buttons → read-only navigation/filters (allowed)
- POST/write submit buttons and execute-control labels → write controls (flagged)

Used by safety-boundary tests. Does not execute anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Forms and submit controls
_FORM_RE = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.IGNORECASE | re.DOTALL)
_METHOD_RE = re.compile(r"""method\s*=\s*["']?(\w+)""", re.IGNORECASE)
_SUBMIT_TYPE_RE = re.compile(r"""type\s*=\s*["']submit["']""", re.IGNORECASE)
_BUTTON_SUBMIT_RE = re.compile(
    r"""<button\b[^>]*\btype\s*=\s*["']submit["'][^>]*>""",
    re.IGNORECASE,
)
_INPUT_SUBMIT_RE = re.compile(
    r"""<input\b[^>]*\btype\s*=\s*["']submit["'][^>]*/?>""",
    re.IGNORECASE,
)

# Explicit execute / agent-control copy that must never appear in dispatch slice
FORBIDDEN_CONTROL_LABELS = (
    "Execute button",
    "Approve button",
    "Launch agent",
    "Run MCP",
)


@dataclass(frozen=True)
class ScanFinding:
    kind: str
    detail: str


def _form_method(attrs: str) -> str:
    match = _METHOD_RE.search(attrs or "")
    if not match:
        # HTML default method is GET
        return "GET"
    return match.group(1).upper()


def find_submit_controls(html: str) -> list[tuple[str, str]]:
    """Return list of (method, snippet) for each submit control inside a form."""
    found: list[tuple[str, str]] = []
    for form in _FORM_RE.finditer(html or ""):
        method = _form_method(form.group(1))
        body = form.group(2)
        for match in list(_BUTTON_SUBMIT_RE.finditer(body)) + list(
            _INPUT_SUBMIT_RE.finditer(body)
        ):
            found.append((method, match.group(0)[:120]))
        # bare type="submit" not caught above (e.g. unusual markup)
        if _SUBMIT_TYPE_RE.search(body) and not (
            _BUTTON_SUBMIT_RE.search(body) or _INPUT_SUBMIT_RE.search(body)
        ):
            found.append((method, "type=\"submit\""))
    return found


def scan_dispatch_slice_for_write_controls(html_slice: str) -> list[ScanFinding]:
    """Scan DISPATCH→HEALTH (or any) HTML slice for write/execute controls.

    Allowed: ``type="submit"`` inside ``method="GET"`` forms (filters).
    Flagged: submit inside non-GET forms; forbidden execute/approve labels.
    """
    findings: list[ScanFinding] = []
    text = html_slice or ""

    for label in FORBIDDEN_CONTROL_LABELS:
        if label in text:
            findings.append(ScanFinding(kind="forbidden_label", detail=label))

    for method, snippet in find_submit_controls(text):
        if method == "GET":
            continue
        findings.append(
            ScanFinding(
                kind="write_form_submit",
                detail=f"method={method} submit control: {snippet}",
            )
        )

    # Submit controls outside any form are treated as write-risk
    stripped = _FORM_RE.sub("", text)
    if _SUBMIT_TYPE_RE.search(stripped):
        findings.append(
            ScanFinding(
                kind="orphan_submit",
                detail='type="submit" outside a form element',
            )
        )

    return findings


def assert_dispatch_slice_read_only(html_slice: str) -> None:
    """Raise AssertionError if write/execute controls are present."""
    findings = scan_dispatch_slice_for_write_controls(html_slice)
    if findings:
        details = "; ".join(f"{f.kind}: {f.detail}" for f in findings)
        raise AssertionError(f"write/execute controls in dispatch slice: {details}")
