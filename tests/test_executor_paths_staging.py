"""Static regression checks against the three real executor order paths.

These tests do not import executors or connect to Hyperliquid. They establish
that the known order call sites remain identifiable before gated integration.
"""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTORS = {
    "aggressive": "aggressive_executor.py",
    "intraday": "intraday_executor.py",
    "daily": "hyperliquid_executor.py",
}


class ExecutorPathContractTests(unittest.TestCase):
    def test_no_executor_market_open_is_reachable_from_execute_trade(self):
        for bot, filename in EXECUTORS.items():
            with self.subTest(bot=bot):
                tree = ast.parse((ROOT / filename).read_text())
                functions = [
                    node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "execute_trade"
                ]
                self.assertEqual(len(functions), 1)
                calls = [
                    node for node in ast.walk(functions[0])
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "market_open"
                ]
                self.assertEqual(calls, [])

                main = next(
                    node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "main"
                )
                self.assertIn("entry_gateway", {
                    arg.arg for arg in main.args.kwonlyargs
                })
                dispatches = [
                    node for node in ast.walk(main)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "execute_trade"
                ]
                self.assertTrue(dispatches)
                self.assertTrue(all(any(
                    keyword.arg == "entry_gateway"
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "entry_gateway"
                    for keyword in call.keywords
                ) for call in dispatches))

    def test_close_path_remains_separate_from_open_path(self):
        for bot, filename in EXECUTORS.items():
            with self.subTest(bot=bot):
                tree = ast.parse((ROOT / filename).read_text())
                fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                          and n.name == "execute_trade")
                self.assertTrue(any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "market_close"
                    for n in ast.walk(fn)
                ))


if __name__ == "__main__":
    unittest.main()
