"""Offline merge-blocking invariants for durable position-increase claims.

No executor modules are imported, no network access, no credentials, no real
or testnet orders. This test intentionally FAILS while an increasing order
can bypass durable per-bot pending-claim persistence.

A passing result would still NOT prove atomic cross-bot exclusion.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "aggressive_executor.py": {"open_long", "open_short", "pyramid_long", "pyramid_short"},
    "intraday_executor.py": {"open_long", "open_short"},
    "hyperliquid_executor.py": {"open_long", "open_short"},
}


def trade_loop(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    loops = [n for n in ast.walk(main)
             if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == "trade"
             and any(isinstance(x, ast.Call)
                     and isinstance(x.func, ast.Name)
                     and x.func.id == "execute_trade" for x in ast.walk(n))]
    if len(loops) != 1:
        raise AssertionError(f"{path}: expected one audited trade dispatch loop")
    return loops[0]


class IncreasingOrdersClaimTests(unittest.TestCase):
    def test_every_increasing_action_is_recorded_before_order_submission(self):
        """New orders and pyramids must use the pre-order persistence branch."""
        for path, required in CASES.items():
            with self.subTest(path=path):
                loop = trade_loop(path)
                assignments = [n for n in ast.walk(loop)
                               if isinstance(n, ast.Assign)
                               and any(isinstance(t, ast.Name) and
                                       t.id in ("is_new_entry", "is_increase")
                                       for t in n.targets)]
                self.assertEqual(len(assignments), 1)
                expression = assignments[0].value
                self.assertIsInstance(expression, ast.Compare)
                self.assertEqual(len(expression.ops), 1)
                self.assertIsInstance(expression.ops[0], ast.In)
                action_set = {n.value for n in expression.comparators[0].elts
                              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                self.assertTrue(required.issubset(action_set),
                                f"{path}: missing pre-submit persisted claim for "
                                f"{sorted(required - action_set)}")
                submits = [n for n in ast.walk(loop)
                           if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name)
                           and n.func.id == "execute_trade"]
                saves = [n for n in ast.walk(loop)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name)
                         and n.func.id in ("save_state", "save_trading_state")]
                self.assertEqual(len(submits), 1)
                self.assertTrue(any(s.lineno < submits[0].lineno for s in saves),
                                f"{path}: no durable claim save before submission")

    def test_pending_pyramid_blocks_but_closes_remain_exempt(self):
        from entry_claim_safety import blocks_entry_with_pending_claim
        pending = {"SOL": {"side": "long", "created_at": "synthetic"}}
        for action in ("open_long", "open_short", "pyramid_long", "pyramid_short"):
            self.assertTrue(blocks_entry_with_pending_claim(
                {"action": action, "hl_coin": "SOL"}, pending))
        self.assertFalse(blocks_entry_with_pending_claim(
            {"action": "close", "hl_coin": "SOL"}, pending))


if __name__ == "__main__":
    unittest.main()
