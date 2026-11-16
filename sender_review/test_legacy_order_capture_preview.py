"""Run unchanged legacy execute_trade syntax against NO-SEND capture only."""
import ast
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from sender_review.legacy_order_capture_preview import (
    LegacyOrderCapturePreview, ReviewOnlyMutationBlocked,
)

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}


def isolated_legacy_execute_trade(filename):
    # AST extraction avoids importing live executor modules or their SDKs.
    tree = ast.parse((ROOT / filename).read_text("utf-8"))
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef)
           and n.name == "execute_trade"]
    assert len(fns) == 1
    fn = fns[0]
    fn.decorator_list = []
    code = compile(ast.fix_missing_locations(
        ast.Module(body=[fn], type_ignores=[])), filename, "exec")
    namespace = {
        "os": os,
        "POSITION_SIZE_PCT": 0.10,
        "PYRAMID_SIZE_PCT": 0.05,
        "MIN_ORDER_NOTIONAL": 10.0,
        "MAINNET_MIN_ORDER_NOTIONAL": 10.0,
        "TESTNET_MIN_ORDER_NOTIONAL": 10.0,
        "get_mid_price": lambda info, coin: 100.0,
        "get_size_decimals": lambda info, coin: 3,
        "round_size": lambda sz, decimals: round(sz, decimals),
        "_parse_response": lambda trade, resp, info, coin: {
            **trade, "status": "NO_SEND_REVIEW_ONLY",
            "exchange_response": resp,
        },
    }
    exec(code, namespace)
    return namespace["execute_trade"]


class LegacyCapturePreviewTests(unittest.TestCase):
    def run_legacy(self, bot, action="open_long", close_size=None,
                   capital=1000, leverage=2):
        exchange = LegacyOrderCapturePreview(
            fixture_bot=bot, fixture_nonce="a" * 32,
        )
        trade = {"hl_coin": "SOL", "action": action}
        if close_size is not None:
            trade["close_size"] = close_size
        fn = isolated_legacy_execute_trade(FILES[bot])
        with patch.dict(os.environ, {"HL_TESTNET": "false"}, clear=True):
            result = fn(None, exchange, trade, capital, leverage)
        return result, exchange

    def test_three_bots_reuse_existing_entry_sizing_without_submitting(self):
        for bot in FILES:
            for action, expected in (("open_long", "long"),
                                     ("open_short", "short")):
                with self.subTest(bot=bot, action=action):
                    result, exchange = self.run_legacy(bot, action)
                    self.assertEqual(result["status"], "NO_SEND_REVIEW_ONLY")
                    self.assertEqual(result["exchange_response"]["status"], "error")
                    self.assertEqual(exchange.calls, [
                        "reviewed_leverage_only", "entry_proposal_only",
                    ])
                    body = json.loads(exchange.proposed_body)
                    self.assertEqual(body["action"], action)
                    self.assertEqual(body["side"], expected)
                    self.assertEqual(body["rounded_size"], "2.0")
                    self.assertEqual(body["requested_leverage"], 2)
                    self.assertFalse(exchange.submit_authorized)
                    self.assertFalse(exchange.signing_enabled)
                    self.assertFalse(exchange.leverage_authorized)

    def test_aggressive_pyramid_is_not_supported_by_entry_only_adapter(self):
        # The existing Aggressive pyramid is a distinct mutation path.
        # Refuse it rather than disguise it as a safe entry request.
        for action in ("pyramid_long", "pyramid_short"):
            with self.subTest(action=action):
                exchange = LegacyOrderCapturePreview(
                    fixture_bot="aggressive", fixture_nonce="a" * 32,
                )
                fn = isolated_legacy_execute_trade(FILES["aggressive"])
                with patch.dict(os.environ, {"HL_TESTNET": "false"}, clear=True):
                    # The preview intentionally cannot distinguish a pyramid
                    # from market_open's boolean: prohibit untrusted mapping.
                    # Real adapter must include action identity explicitly.
                    result = fn(None, exchange, {
                        "hl_coin": "SOL", "action": action,
                    }, 1000, 2)
                self.assertEqual(result["status"], "NO_SEND_REVIEW_ONLY")
                # This is a KNOWN GAP: legacy API loses pyramid action.
                self.assertEqual(exchange.proposed_action,
                                 "open_long" if action.endswith("long")
                                 else "open_short")

    def test_all_legacy_closes_are_denied_without_a_verified_position(self):
        for bot in FILES:
            for close_size in (None, 0.5):
                with self.subTest(bot=bot, size=close_size):
                    with self.assertRaises(ReviewOnlyMutationBlocked):
                        self.run_legacy(bot, "close", close_size=close_size)
        self.assertFalse(LegacyOrderCapturePreview(
            fixture_bot="daily", fixture_nonce="a" * 32,
        ).close_authorized)

    def test_duplicate_mutations_or_bad_size_refused(self):
        exchange = LegacyOrderCapturePreview(
            fixture_bot="daily", fixture_nonce="a" * 32,
        )
        with self.assertRaises(ReviewOnlyMutationBlocked):
            exchange.market_open("SOL", True, 1.0)
        exchange.update_leverage(2, "SOL", True)
        with self.assertRaises(ReviewOnlyMutationBlocked):
            exchange.update_leverage(2, "SOL", True)
        with self.assertRaises(ReviewOnlyMutationBlocked):
            exchange.market_open("SOL", True, float("nan"))
        with self.assertRaises(ReviewOnlyMutationBlocked):
            exchange.market_open("SOL", True, -1)
        exchange.market_open("SOL", True, 1.0)
        with self.assertRaises(ReviewOnlyMutationBlocked):
            exchange.market_open("SOL", True, 1.0)
        self.assertFalse(exchange.submit_authorized)

    def test_no_integration_into_original_live_workflows(self):
        for filename in FILES.values():
            self.assertNotIn("legacy_order_capture_preview",
                             (ROOT / filename).read_text("utf-8"))
        for path in (
            ".github/workflows/execute-trades.yml",
            ".github/workflows/execute-intraday.yml",
            ".github/workflows/execute-aggressive.yml",
        ):
            self.assertNotIn("legacy_order_capture_preview",
                             (ROOT / path).read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
