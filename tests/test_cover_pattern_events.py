"""Verify recoverable cover-pattern websocket failure handling is wired."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class CoverPatternEventTests(unittest.TestCase):
    def test_sender_emits_constrained_unavailable_reasons_instead_of_swallowing_failures(self) -> None:
        source = Path("src/ws/ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        sender = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_send_cover_pattern"
        )
        sender_source = ast.get_source_segment(source, sender) or ""

        self.assertIn('"type": "cover_pattern_unavailable"', sender_source)
        self.assertIn('"reason": exc.reason', sender_source)
        self.assertIn('"reason": "generation_failed"', sender_source)
        self.assertIn("await ui._send(payload)", sender_source)


if __name__ == "__main__":
    unittest.main()
