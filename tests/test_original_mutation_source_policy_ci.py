"""Offline source-to-policy drift audit for PR #40 original trading bots.

Checks the REAL three original source files without importing or executing
any of them. This is an OPEN-RISK BASELINE, not proof of signer removal:
all three original execute_trade functions can still directly mutate an
Exchange object. The audit intentionally fails on unreviewed changes to
that known risk inventory until an independently approved cutover updates it.

Connects those actual mutation callsite categories to the existing
synthetic, non-authorizing review policy. No exchange, signing key, SQL,
network or order is involved. Static AST checks are NOT proof of absence
of aliases, dynamic code, imports or other signing routes.
"""
import ast
from collections import Counter
from pathlib import Path
import unittest

from offline_three_bot_mutation_review_ci import (
    review_original_bot_mutation_offline,
)

ROOT = Path(__file__).resolve().parents[1]
BOTS = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}
ACCOUNT = "0x" + "1" * 40
EXPECTED = Counter({
    "market_close": 2,
    "update_leverage": 1,
    "market_open": 1,
})


def audit_direct_original_exchange_calls(source):
    """Return only known baseline or a review-needed reason, never authority."""
    try:
        tree = ast.parse(source)
    except (TypeError, SyntaxError, ValueError):
        return {"state": "hold", "known_baseline": False,
                "reason": "source unreadable"}
    executions = [node for node in tree.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == "execute_trade"]
    if len(executions) != 1:
        return {"state": "hold", "known_baseline": False,
                "reason": "original trade function changed"}
    fn = executions[0]
    if not (len(fn.args.args) >= 2 and fn.args.args[1].arg == "exchange"):
        return {"state": "hold", "known_baseline": False,
                "reason": "exchange parameter changed"}

    all_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "exchange"
    ]
    inside = [node for node in ast.walk(fn)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name)
              and node.func.value.id == "exchange"]
    observed = Counter(call.func.attr for call in all_calls)
    if observed != EXPECTED or len(inside) != len(all_calls):
        return {"state": "hold", "known_baseline": False,
                "reason": "new, removed or relocated exchange mutation"}

    closes = [node for node in inside
              if node.func.attr == "market_close"]
    if Counter(tuple(sorted(kw.arg for kw in node.keywords))
               for node in closes) != Counter({(): 1, ("sz",): 1}):
        return {"state": "hold", "known_baseline": False,
                "reason": "original close sizing/fallback changed"}

    # Characterize the current direct risk rather than treating its
    # presence as acceptance. This flag cannot approve a single order.
    return {"state": "hold", "known_baseline": True,
            "reason": "original signer-backed mutation calls still present",
            "direct_mutation_calls": 4,
            "unsized_close_still_present": True,
            "trading_authorized": False}


def classify(bot, action, *, close_size=None):
    trade = {
        "action": action, "hl_coin": "SOL",
        "side": "short" if action.endswith("_short") else "long",
    }
    if close_size is not None:
        trade["close_size"] = close_size
    return review_original_bot_mutation_offline(
        verified_bot=bot, trade=trade, rounded_size="0.025",
        pinned_environment="mainnet", pinned_account=ACCOUNT,
    )


class OriginalTradeSourceToPolicyTests(unittest.TestCase):
    def test_actual_three_bots_have_exact_12_direct_mutation_call_baseline(self):
        for bot, path in BOTS.items():
            with self.subTest(bot=bot):
                source = (ROOT / path).read_text(encoding="utf-8")
                evidence = audit_direct_original_exchange_calls(source)
                self.assertEqual(evidence["state"], "hold")
                self.assertTrue(evidence.get("known_baseline"))
                self.assertEqual(evidence["direct_mutation_calls"], 4)
                self.assertTrue(evidence["unsized_close_still_present"])
                self.assertFalse(evidence["trading_authorized"])

    def test_original_mutation_types_map_to_request_only_or_hold_not_orders(self):
        for bot in BOTS:
            for action, expected_class in (
                ("open_long", "new_entry"),
                ("open_short", "new_entry"),
                ("close", "close"),
                ("update_leverage", "leverage_change"),
            ):
                with self.subTest(bot=bot, action=action):
                    result = classify(bot, action, close_size="0.025")
                    self.assertEqual(result.action_class, expected_class)
                    self.assertEqual(
                        result.state,
                        "request_only" if expected_class == "new_entry" else "hold",
                    )
                    self.assertFalse(result.submit_authorized)
                    self.assertFalse(result.close_authorized)
                    self.assertFalse(result.ownership_verified)
                    if expected_class != "new_entry":
                        self.assertIsNone(result.request_json)
            # The old market_close(coin) fallback must NEVER be equivalent
            # to a vetted, explicitly sized reduce-only close.
            unsized = classify(bot, "close")
            self.assertEqual(unsized.state, "hold")
            self.assertIn("missing", unsized.reason.lower())

        for action in ("pyramid_long", "pyramid_short"):
            result = classify("aggressive", action)
            self.assertEqual(result.action_class, "pyramid_increase")
            self.assertEqual(result.state, "hold")
            self.assertIsNone(result.request_json)
            self.assertFalse(result.submit_authorized)

    def test_added_removed_or_relocated_exchange_calls_fail_baseline(self):
        original = (ROOT / BOTS["aggressive"]).read_text(encoding="utf-8")
        experiments = (
            original.replace("exchange.market_open(", "exchange.order(", 1),
            original.replace(
                "resp = exchange.market_open(",
                "exchange.cancel(coin)\n    resp = exchange.market_open(", 1,
            ),
            original.replace(
                "else exchange.market_close(coin)",
                "else exchange.market_close(coin, sz=close_size)", 1,
            ),
            original.replace("def execute_trade(", "def execute_trade_unreviewed(", 1),
            "broken python ?",
        )
        for source in experiments:
            with self.subTest(length=len(source)):
                decision = audit_direct_original_exchange_calls(source)
                self.assertEqual(decision["state"], "hold")
                self.assertFalse(decision["known_baseline"])
                self.assertNotIn("trading_authorized", decision)

    def test_no_original_executor_modules_imported(self):
        import sys
        for module in ("hyperliquid_executor", "intraday_executor",
                       "aggressive_executor", "hyperliquid.exchange"):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
