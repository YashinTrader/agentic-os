"""Encoding-tolerant CLI output without changing stored Unicode data."""

import sys


def configure_console() -> None:
    """Keep stream encodings, replacing characters they cannot represent.

    Captured streams such as StringIO need no configuration.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
