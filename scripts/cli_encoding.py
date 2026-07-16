#!/usr/bin/env python3
"""Encoding-safe stdout/stderr helpers for Windows (cp1252) and similar locales.

Task and handoff CLIs print arbitrary YAML/Markdown text that may contain
characters outside the active stdout codec (e.g. U+2192 RIGHTWARDS ARROW,
U+2014 EM DASH under PYTHONIOENCODING=cp1252). File content is never mutated;
only stream write behavior is made tolerant.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO


def configure_stdio(*, errors: str = "replace") -> None:
    """Reconfigure stdout/stderr so unencodable characters do not raise.

    Prefers TextIO.reconfigure(errors=...) which keeps the active encoding
    (including PYTHONIOENCODING) but switches the error handler. Falls back
    silently when reconfigure is unavailable or fails (closed/redirected
    streams, non-text wrappers).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors=errors)
        except Exception:
            # Closed streams, non-reconfigurable wrappers, or restricted envs.
            continue


def encode_for_stream(text: str, stream: TextIO | None = None) -> str:
    """Return *text* encoded/decoded for *stream* with replacement errors.

    Useful when a stream cannot be reconfigured but still accepts str writes.
    """
    target = stream if stream is not None else sys.stdout
    encoding = getattr(target, "encoding", None) or sys.getdefaultencoding() or "utf-8"
    stream_errors = getattr(target, "errors", None) or "strict"
    if stream_errors != "strict":
        return text
    try:
        text.encode(encoding, errors="strict")
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def safe_print(
    *args: Any,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    """print() wrapper that never raises UnicodeEncodeError on narrow codecs."""
    target: TextIO = file if file is not None else sys.stdout
    text = sep.join(str(a) for a in args) + end
    safe = encode_for_stream(text, target)
    try:
        target.write(safe)
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "utf-8"
        buffer = getattr(target, "buffer", None)
        if buffer is not None:
            buffer.write(safe.encode(encoding, errors="replace"))
            if end and not safe.endswith(end):
                buffer.write(end.encode(encoding, errors="replace"))
        else:
            # Last resort: drop unencodable chars rather than crash the CLI.
            target.write(text.encode(encoding, errors="replace").decode(encoding, errors="ignore"))
    if flush:
        try:
            target.flush()
        except Exception:
            pass


def install_encode_safe_stdio(*, errors: str = "replace") -> None:
    """Public entry point for CLIs: call once at process start (before prints)."""
    configure_stdio(errors=errors)
