"""Static contract: real Intraday order dispatch is guarded when trial is ON."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IntradayTrialDispatchTests(unittest.TestCase):
    def test_trial_guard_precedes_market_open(self):
        tree = ast.parse((ROOT / "intraday_executor.py").read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "execute_trade")
        guard = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                 and any(isinstance(x, ast.Constant)
                         and x.value == "INTRADAY_ENTRY_SAFETY_TRIAL"
                         for x in ast.walk(n.test))]
        self.assertEqual(len(guard), 1)
        open_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "market_open"]
        close_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "market_close"]
        self.assertEqual(len(open_calls), 1)
        self.assertTrue(close_calls)
        self.assertLess(max(n.lineno for n in close_calls), guard[0].lineno)
        self.assertLess(guard[0].lineno, open_calls[0].lineno)
        self.assertTrue(any(isinstance(n, ast.Return) for n in guard[0].body))


if __name__ == "__main__":
    unittest.main()
