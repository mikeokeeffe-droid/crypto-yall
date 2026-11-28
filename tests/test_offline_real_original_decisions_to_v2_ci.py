"""Run actual source-extracted original decision functions through V2 review.

No import of live executors, Hyperliquid clients, secrets or network. AST
selection compiles ONLY the existing decide_trades functions against synthetic
signals. This is offline strategy compatibility, not trusted exchange data,
execution, close authorization, credential isolation or a deployed cutover.
"""
import ast
import json
from pathlib import Path
import sys
import unittest

from offline_original_signal_projection_ci import _TICKERS
from offline_signer_free_read_bootstrap_ci import (
    bootstrap_original_read_only_offline,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40
BOT_SOURCE = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}


def original_decider(bot):
    """Load one reviewed function body, never the original module."""
    filename = BOT_SOURCE[bot]
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"),
                     filename=filename)
    matches = [node for node in tree.body
               if isinstance(node, ast.FunctionDef)
               and node.name == "decide_trades"]
    if len(matches) != 1:
        raise AssertionError("source contract changed: decide_trades")
    fn = matches[0]
    # Fail closed if future deciders import/send/execute commands directly.
    forbidden = {"get_client", "market_open", "market_close",
                 "update_leverage", "__import__", "exec", "eval",
                 "subprocess", "connect", "send_order", "open"}
    for node in ast.walk(fn):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise AssertionError("unreviewed import in original decider")
        if isinstance(node, ast.Call):
            name = (node.func.id if isinstance(node.func, ast.Name)
                    else node.func.attr if isinstance(node.func, ast.Attribute)
                    else None)
            if name in forbidden:
                raise AssertionError("unexpected mutating call in decider")
    fn.decorator_list = []
    only = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    ns = {"HL_TICKER_MAP": dict(_TICKERS),
          "HL_SYMBOL_MAP": dict(_TICKERS)}
    exec(compile(only, filename, "exec"), ns)
    return ns["decide_trades"]


def snap():
    return {
        "environment": "testnet", "account": ACCOUNT,
        "user_state": {"marginSummary": {"accountValue": "150"},
                       "assetPositions": []},
        "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
        "all_mids": {"SOL": "125", "AVAX": "25"},
        "meta": {"universe": [
            {"name": "SOL", "szDecimals": 3},
            {"name": "AVAX", "szDecimals": 2},
        ]},
    }


def view(bot):
    result = bootstrap_original_read_only_offline(
        verified_bot=bot, pinned_environment="testnet",
        pinned_account=ACCOUNT, snapshot=snap(),
    )
    if result is None:
        raise AssertionError("synthetic bootstrap refused")
    return result


def decide(bot, signals, positions=None, *, max_positions=2,
           pyramid_state=None):
    decider = original_decider(bot)
    args = (signals, positions if positions is not None else {},
            max_positions)
    if bot == "aggressive":
        return decider(*args, pyramid_state if pyramid_state is not None else {})
    return decider(*args)


def signal(action, confidence=.8, osc=.6, *, pyramid=False):
    return {
        "action": action, "bull_conf": confidence,
        "bear_conf": confidence, "osc": osc, "pyramid_added": pyramid,
    }


class OriginalDecisionsToSignerFreeV2Tests(unittest.TestCase):
    def test_actual_open_decisions_all_three_feed_review_only_v2(self):
        for bot in BOT_SOURCE:
            with self.subTest(bot=bot):
                trades = decide(bot, {
                    "SOL-USD": signal("buy", .85),
                    "AVAX-USD": signal("enter_short", .65),
                })
                self.assertEqual(len(trades), 2)
                self.assertEqual(
                    {(t["hl_coin"], t["action"]) for t in trades},
                    {("SOL", "open_long"), ("AVAX", "open_short")},
                )
                client = view(bot)
                for original in trades:
                    result = client.draft_original_candidate_review(
                        candidate=original, rounded_size="0.025",
                        requested_leverage=2,
                    )
                    self.assertEqual(result.state, "review_only")
                    self.assertFalse(result.submit_authorized)
                    self.assertFalse(result.leverage_applied)
                    data = json.loads(result.review_json)
                    self.assertEqual(data["hl_coin"], original["hl_coin"])
                    self.assertEqual(data["action"], original["action"])
                    self.assertNotIn("reason", data)
                    self.assertNotIn("priority", data)
                    self.assertNotIn("confidence", data)

    def test_original_daily_fresh_only_vs_intraday_sync_remains_non_authorizing(self):
        for bot in BOT_SOURCE:
            with self.subTest(bot=bot):
                trades = decide(bot, {"SOL-USD": signal("hold_long")})
                if bot == "daily":
                    self.assertEqual(trades, [])
                else:
                    self.assertEqual(len(trades), 1)
                    self.assertEqual(trades[0]["action"], "open_long")
                    review = view(bot).draft_original_candidate_review(
                        candidate=trades[0], rounded_size="0.025",
                        requested_leverage=2,
                    )
                    self.assertEqual(review.state, "review_only")
                    self.assertFalse(review.submit_authorized)
                    self.assertFalse(review.leverage_applied)

    def test_actual_original_protective_closes_cannot_become_entries(self):
        for bot in BOT_SOURCE:
            with self.subTest(bot=bot):
                trades = decide(
                    bot, {"SOL-USD": signal("sell_exit")},
                    {"SOL": {"size": 0.5, "unrealized_pnl": 2}},
                )
                self.assertEqual(len(trades), 1)
                self.assertEqual(trades[0]["action"], "close")
                self.assertEqual(trades[0]["close_size"], 0.5)
                result = view(bot).draft_original_candidate_review(
                    candidate=trades[0], rounded_size="0.025",
                    requested_leverage=2,
                )
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.review_json)
                self.assertFalse(result.submit_authorized)

    def test_original_aggressive_pyramid_stays_hold_and_never_maps_to_open(self):
        trades = decide(
            "aggressive", {"SOL-USD": signal("hold_long", pyramid=True)},
            {"SOL": {"size": 0.5, "unrealized_pnl": 2}},
            pyramid_state={},
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "pyramid_long")
        result = view("aggressive").draft_original_candidate_review(
            candidate=trades[0], rounded_size="0.025",
            requested_leverage=2,
        )
        self.assertEqual(result.state, "hold")
        self.assertIsNone(result.review_json)
        self.assertFalse(result.submit_authorized)

    def test_original_same_cycle_close_and_reverse_entry_both_hold(self):
        # The original deciders close a long and propose opening short in
        # the same cycle. A close is NOT a proven fill or a cleared position.
        for bot in BOT_SOURCE:
            with self.subTest(bot=bot):
                decisions = decide(
                    bot, {"SOL-USD": signal("enter_short")},
                    {"SOL": {"size": 0.5, "unrealized_pnl": 2}},
                )
                self.assertEqual(len(decisions), 2)
                self.assertEqual(
                    [item["action"] for item in decisions],
                    ["close", "open_short"],
                )
                for index in range(len(decisions)):
                    result = view(bot).draft_review_from_complete_decision_batch(
                        decisions=decisions, selected_index=index,
                        rounded_size="0.025", requested_leverage=2,
                    )
                    self.assertEqual(result.state, "hold")
                    self.assertIsNone(result.review_json)
                    self.assertFalse(result.submit_authorized)

    def test_complete_batch_accepts_distinct_new_entries_for_review_only(self):
        for bot in BOT_SOURCE:
            with self.subTest(bot=bot):
                decisions = decide(bot, {
                    "SOL-USD": signal("buy", .8),
                    "AVAX-USD": signal("enter_short", .7),
                })
                self.assertEqual(len(decisions), 2)
                for index, proposal in enumerate(decisions):
                    draft = view(bot).draft_review_from_complete_decision_batch(
                        decisions=decisions, selected_index=index,
                        rounded_size="0.025", requested_leverage=2,
                    )
                    self.assertEqual(draft.state, "review_only")
                    self.assertFalse(draft.submit_authorized)
                    self.assertFalse(draft.leverage_applied)
                    self.assertEqual(
                        json.loads(draft.review_json)["hl_coin"],
                        proposal["hl_coin"],
                    )

    def test_batch_unknown_duplicate_and_pyramid_actions_hold_all(self):
        for bot in BOT_SOURCE:
            entries = decide(bot, {"SOL-USD": signal("buy")})
            self.assertEqual(len(entries), 1)
            bad_batches = [
                [entries[0], entries[0]],
                [{**entries[0], "cloid": "spoofed"}],
                [{**entries[0], "action": "pyramid_long"}],
                [{**entries[0], "action": "close"}],
                entries + [dict(entries[0], hl_coin="AVAX",
                                ticker="AVAX-USD",
                                unexpected_future_flag=True)],
            ]
            for batch in bad_batches:
                with self.subTest(bot=bot, batch=batch):
                    result = view(bot).draft_review_from_complete_decision_batch(
                        decisions=batch, selected_index=0,
                        rounded_size="0.025", requested_leverage=2,
                    )
                    self.assertEqual(result.state, "hold")
                    self.assertIsNone(result.review_json)
                    self.assertFalse(result.submit_authorized)
            self.assertEqual(
                view(bot).draft_review_from_complete_decision_batch(
                    decisions=[], selected_index=0,
                    rounded_size="0.025", requested_leverage=2,
                ).state, "hold",
            )

    def test_extraction_does_not_import_signers_or_execute_original_modules(self):
        for bot in BOT_SOURCE:
            self.assertTrue(callable(original_decider(bot)))
        for name in (
            "hyperliquid_executor", "intraday_executor",
            "aggressive_executor", "eth_account",
            "hyperliquid.exchange",
        ):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
