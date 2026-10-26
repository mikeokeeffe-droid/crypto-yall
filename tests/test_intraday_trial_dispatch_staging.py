"""Static contract: staging-only PR does not wire a trial into live dispatch."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class IntradayProductionIsolationTests(unittest.TestCase):
    def test_live_executor_has_no_staging_trial_guard(self):
        tree = ast.parse((ROOT / "intraday_executor.py").read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "execute_trade")
        self.assertFalse(any(isinstance(n, ast.Constant)
                             and n.value == "INTRADAY_ENTRY_SAFETY_TRIAL"
                             for n in ast.walk(fn)))
        self.assertFalse(any(isinstance(n, ast.Name)
                             and n.id == "observe_intraday_entry"
                             for n in ast.walk(fn)))
        self.assertTrue(any(isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "market_open"
                            for n in ast.walk(fn)))

if __name__ == "__main__":
    unittest.main()
