"""Static, offline audit of the original executors' kill-switch exit path.

This is a characterization test, not an endorsement of the behavior. It never
imports executors, starts a client, or places orders. A passing result confirms
the documented risk: kill switches can prevent automated protective exits.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("aggressive_executor.py", "kill_switch_off"),
    ("intraday_executor.py", "kill_switch_off"),
    ("hyperliquid_executor.py", "check_kill_switch"),
)

class KillSwitchExitPathAudit(unittest.TestCase):
    def test_kill_switch_precedes_all_trade_dispatch(self):
        for filename, guard_name in CASES:
            with self.subTest(bot=filename):
                tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
                main = next(node for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name == "main")
                guards = [
                    node for node in ast.walk(main)
                    if isinstance(node, ast.If)
                    and isinstance(node.test, ast.Call)
                    and isinstance(node.test.func, ast.Name)
                    and node.test.func.id == guard_name
                ]
                submits = [
                    node for node in ast.walk(main)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "execute_trade"
                ]
                self.assertEqual(len(guards), 1)
                self.assertEqual(len(submits), 1)
                guard = guards[0]
                self.assertLess(guard.lineno, submits[0].lineno)
                self.assertTrue(any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "sys"
                    and node.func.attr == "exit"
                    for statement in guard.body for node in ast.walk(statement)
                ), "expected early sys.exit in original kill-switch path")

if __name__ == "__main__":
    unittest.main()
