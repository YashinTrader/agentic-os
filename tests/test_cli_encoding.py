from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from cli_encoding import (  # noqa: E402
    configure_stdio,
    encode_for_stream,
    install_encode_safe_stdio,
    safe_print,
)


class CliEncodingTests(unittest.TestCase):
    def test_encode_for_stream_replaces_unencodable_chars(self) -> None:
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        text = "A \u2192 B \u2014 C"
        # EM DASH is in cp1252; RIGHTWARDS ARROW is not.
        encoded = encode_for_stream(text, stream)
        self.assertIn("A ", encoded)
        self.assertIn(" B ", encoded)
        self.assertIn(" C", encoded)
        # Must be strictly encodable as cp1252 after sanitizing.
        encoded.encode("cp1252", errors="strict")
        self.assertNotEqual(encoded, text)

    def test_encode_for_stream_preserves_when_already_encodable(self) -> None:
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        text = "plain ASCII and em dash \u2014 ok"
        self.assertEqual(encode_for_stream(text, stream), text)

    def test_safe_print_does_not_raise_on_cp1252_buffer(self) -> None:
        buf = io.BytesIO()
        stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict", write_through=True)
        safe_print("arrow \u2192 here", file=stream, end="")
        stream.flush()
        raw = buf.getvalue()
        self.assertTrue(raw)
        # Decoded with replace must retain ASCII anchors.
        decoded = raw.decode("cp1252", errors="replace")
        self.assertIn("arrow", decoded)
        self.assertIn("here", decoded)

    def test_install_encode_safe_stdio_is_idempotent(self) -> None:
        # Smoke: should not raise even when called repeatedly.
        install_encode_safe_stdio()
        configure_stdio(errors="replace")
        install_encode_safe_stdio()


if __name__ == "__main__":
    unittest.main()
