"""Characterize the original leverage-error path without any real orders.

The three original execute_trade functions currently catch update_leverage
errors and proceed to market_open. This is an unresolved live risk, NOT a
passing safety gate. An offline non-signing sink must never represent that
sequence as a valid leverage-bound draft.
"""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from offline_leverage_bound_entry_draft_ci import OfflineLeverageBoundEntrySink

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}
ACCOUNT = "0x" + "1" * 40


def extracted(bot):
    filename = FILES[bot]
    tree = ast.parse((ROOT / filename).read_text(encoding="utf8"))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "execute_trade"]
    if len(functions) != 1:
        raise AssertionError("trade function inventory changed")
    node = functions[0]
    node.decorator_list = []
    standalone = ast.fix_missing_locations(
        ast.Module(body=[node], type_ignores=[]))
    namespace = {
        "os": os,
        "POSITION_SIZE_PCT": .1, "PYRAMID_SIZE_PCT": .05,
        "MIN_ORDER_NOTIONAL": 10.,
        "MAINNET_MIN_ORDER_NOTIONAL": 10.,
        "TESTNET_MIN_ORDER_NOTIONAL": 10.,
        "get_mid_price": lambda info, coin: 100.,
        "get_size_decimals": lambda info, coin: 3,
        "round_size": lambda size, digits: round(size, digits),
        "_parse_response": lambda trade, resp, info, coin:
            {"status": resp.get("status")},
    }
    exec(compile(standalone, filename, "exec"), namespace)
    return namespace["execute_trade"]


class OriginalLeverageFailureTests(unittest.TestCase):
    def test_error_is_caught_and_original_still_attempts_open_known_risk(self):
        for bot in FILES:
            with self.subTest(bot=bot):
                trade = {"hl_coin": "SOL", "action": "open_long"}
                sink = OfflineLeverageBoundEntrySink(
                    bot=bot, trade=trade, environment="mainnet",
                    account=ACCOUNT)
                def failed_leverage(leverage, coin, cross):
                    # Preserve the real original error path, while NEVER
                    # invoking the exchange or granting a leverage proposal.
                    sink.events.append(("leverage_error", coin))
                    raise OSError("synthetic leverage endpoint unavailable")
                sink.update_leverage = failed_leverage
                with patch.dict(os.environ, {"HL_TESTNET": "false"}, clear=True):
                    outcome = extracted(bot)(None, sink, trade, 1000, 2)
                self.assertEqual(outcome["status"], "offline_hold")
                self.assertEqual([event[0] for event in sink.events],
                                 ["leverage_error", "entry_request_only"])
                # Crucial distinction: original attempts open, but the
                # leverage-bound V2 draft cannot be built or sent.
                self.assertEqual(sink.last_draft.state, "hold")
                self.assertIsNone(sink.last_draft.review_json)
                self.assertFalse(sink.last_draft.submit_authorized)
                self.assertFalse(sink.last_draft.leverage_applied)

    def test_failed_underlying_sink_cannot_leave_prior_leverage_draft(self):
        sink = OfflineLeverageBoundEntrySink(
            bot="daily",
            trade={"hl_coin": "SOL", "action": "open_long"},
            environment="mainnet", account=ACCOUNT)
        sink.update_leverage(2, "SOL", True)
        original = OfflineLeverageBoundEntrySink.__mro__[1].update_leverage
        def broken(self, leverage, coin, cross):
            raise OSError("synthetic failure")
        OfflineLeverageBoundEntrySink.__mro__[1].update_leverage = broken
        try:
            with self.assertRaises(OSError):
                sink.update_leverage(3, "SOL", True)
        finally:
            OfflineLeverageBoundEntrySink.__mro__[1].update_leverage = original
        sink.market_open("SOL", True, 2.)
        self.assertEqual(sink.last_draft.state, "hold")
        self.assertIsNone(sink.last_draft.review_json)
        self.assertFalse(sink.last_draft.submit_authorized)


if __name__ == "__main__":
    unittest.main()
