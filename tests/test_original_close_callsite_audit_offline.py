"""Static characterization of original close-order call sites.

Does not import executors or invoke Hyperliquid. The SDK's market_close
implementation might internally set reduce_only; this test cannot verify that.
It records that the original call sites do not explicitly enforce it, and
that absent/nonpositive close sizes fall back to unsized market_close.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ("aggressive_executor.py", "intraday_executor.py",
         "hyperliquid_executor.py")

class OriginalCloseCallSiteAudit(unittest.TestCase):
    def test_original_close_paths_rely_on_sdk_and_allow_unsized_fallback(self):
        for filename in FILES:
            with self.subTest(filename=filename):
                tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
                executor = next(n for n in tree.body
                                if isinstance(n, ast.FunctionDef)
                                and n.name == "execute_trade")
                closes = [n for n in executor.body if isinstance(n, ast.If)
                          and isinstance(n.test, ast.Compare)
                          and isinstance(n.test.left, ast.Subscript)
                          and isinstance(n.test.left.value, ast.Name)
                          and n.test.left.value.id == "trade"
                          and any(isinstance(c, ast.Constant) and c.value == "close"
                                  for c in n.test.comparators)]
                self.assertEqual(len(closes), 1)
                close = closes[0]
                calls = [n for n in ast.walk(close)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "market_close"]
                self.assertEqual(len(calls), 2)
                self.assertTrue(any(len(n.keywords) == 0 for n in calls),
                                "expected original unsized close fallback")
                self.assertTrue(any(any(k.arg == "sz" for k in n.keywords)
                                    for n in calls))
                self.assertFalse(any(any(k.arg in ("reduce_only", "reduceOnly")
                                         for k in n.keywords) for n in calls),
                                 "explicit reduce-only handling changed: review audit")
                self.assertTrue(all(n.lineno < next(
                    n2.lineno for n2 in ast.walk(executor)
                    if isinstance(n2, ast.Call)
                    and isinstance(n2.func, ast.Attribute)
                    and n2.func.attr == "market_open") for n in calls))

if __name__ == "__main__":
    unittest.main()
