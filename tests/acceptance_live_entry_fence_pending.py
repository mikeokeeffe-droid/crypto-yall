"""Offline static guard: no production executor may silently bypass shared entry fencing.

This is intentionally a FAIL-CLOSED release acceptance test. It is expected
to fail until a reviewed atomic reservation adapter is integrated into each
real executor. Do not add it to green CI before that integration.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ("aggressive_executor.py", "intraday_executor.py", "hyperliquid_executor.py")

class LiveEntryFenceAcceptance(unittest.TestCase):
    def test_each_real_market_open_is_preceded_by_atomic_entry_gate(self):
        for filename in FILES:
            with self.subTest(filename=filename):
                tree = ast.parse((ROOT / filename).read_text())
                fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                          and n.name == "execute_trade")
                calls = [n for n in ast.walk(fn)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "market_open"]
                self.assertEqual(len(calls), 1)
                # Explicit acceptance marker only; never infer protection from
                # the mock-only shared_entry_gate_staging module.
                self.assertIn("atomic_entry_permit", ast.get_source_segment(
                    (ROOT / filename).read_text(), fn) or "",
                    "real executor lacks reviewed atomic entry gate")

if __name__ == "__main__":
    unittest.main()
