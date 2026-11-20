"""Compare exact AST-isolated existing strategy decisions with pure HOLD copies."""
import ast
from pathlib import Path
import unittest

from sender_review.pure_strategy_decisions_offline import (
    TICKER_TO_COIN, inspect_pure_strategy_decisions_offline,
)
from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}


def extract_original_decide_trades(bot):
    # AST extract ONE pure original decision; do not import live executors.
    filename = FILES[bot]
    tree = ast.parse((ROOT / filename).read_text("utf-8"))
    nodes = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "decide_trades"]
    assert len(nodes) == 1
    namespace = {
        "HL_TICKER_MAP": dict(TICKER_TO_COIN),
        "HL_SYMBOL_MAP": dict(TICKER_TO_COIN),
        "print": lambda *args, **kwargs: None,
    }
    code = compile(ast.fix_missing_locations(
        ast.Module(body=[nodes[0]], type_ignores=[])), filename, "exec")
    exec(code, namespace)
    return namespace["decide_trades"]


def view(positions=None, equity="150"):
    positions = positions or []
    account = {
        "marginSummary": {"accountValue": equity},
        "assetPositions": [{
            "position": {
                "coin": coin, "szi": str(size), "entryPx": "100",
                "unrealizedPnl": str(pnl), "leverage": {"value": 2},
            },
        } for coin, size, pnl in positions],
    }
    return extract_signer_free_account_view_offline(user_state=account)


class PureStrategyDecisionCompatibilityTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertEqual(result.state, "PURE_LOCAL_DECISIONS_FIXTURE_HOLD")
        for flag in (
            "exchange_origin_authenticated", "account_scope_verified",
            "ownership_verified", "live_signal_verified",
            "market_risk_verified", "protection_runner_verified",
            "runtime_identity_authenticated", "durable_fence_reserved",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, flag), False, flag)

    def compare(self, bot, signals, positions, slots, pyramids=None):
        account = view(positions)
        self.assertTrue(account.fixture_parsed, account.reason)
        pure = inspect_pure_strategy_decisions_offline(
            bot=bot, signals=signals, account_view=account,
            max_positions=slots, pyramid_state=pyramids,
        )
        self.assert_no_authority(pure)
        original = extract_original_decide_trades(bot)
        args = [signals, account.positions, slots]
        if bot == "aggressive":
            args.append(pyramids or {})
        actual = original(*args)
        self.assertEqual(list(pure.proposed_actions), actual)
        return actual

    def test_daily_original_fresh_entry_and_liquidate_semantics(self):
        signals = {
            "SOL-USD": {"action": "sell_exit"},
            "AVAX-USD": {"action": "liquidate"},
            "LINK-USD": {"action": "buy", "bull_conf": 0.8},
            "XRP-USD": {"action": "enter_short", "bear_conf": 0.9},
            "ONDO-USD": {"action": "hold_long"},
        }
        actions = self.compare(
            "daily", signals, [("SOL", 0.4, 1), ("AVAX", -0.2, -1)], 2,
        )
        self.assertEqual([x["action"] for x in actions],
                         ["close", "close", "open_short", "open_long"])
        self.assertFalse(any(x["hl_coin"] == "ONDO" for x in actions))

    def test_intraday_priority_and_hold_sync_preserved_as_untrusted_proposals(self):
        signals = {
            "SOL-USD": {"action": "hold_long", "osc": 0.1},
            "AVAX-USD": {"action": "enter_short", "osc": -0.9},
            "LINK-USD": {"action": "buy", "osc": 0.5},
        }
        result = self.compare("intraday", signals, [], 2)
        self.assertEqual([x["hl_coin"] for x in result], ["AVAX", "LINK"])
        self.assertEqual(result[0]["priority"], 0.9)

    def test_existing_flip_to_close_then_new_proposal_same_coin(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                info = {"action": "buy", "bull_conf": 0.8, "osc": 0.8}
                actions = self.compare(
                    bot, {"SOL-USD": info}, [("SOL", -0.3, 1)], 1,
                    {} if bot == "aggressive" else None,
                )
                self.assertEqual([x["action"] for x in actions],
                                 ["close", "open_long"])
                # This is historical decision parity, NOT safe account-wide
                # ownership/reconciliation; real sender must not blindly
                # open when a prior close acknowledgement is unknown.

    def test_aggressive_profitable_pyramids_and_two_add_limit(self):
        signals = {
            "SOL-USD": {"action": "hold_long", "osc": 0.3,
                        "pyramid_added": True},
            "AVAX-USD": {"action": "hold_short", "osc": -0.4,
                         "pyramid_added": True},
            "LINK-USD": {"action": "hold_long", "osc": 0.9},
        }
        positions = [("SOL", 0.4, 3), ("AVAX", -0.2, -1)]
        result = self.compare(
            "aggressive", signals, positions, 3,
            {"SOL": 1, "AVAX": 0},
        )
        self.assertEqual([r["action"] for r in result],
                         ["pyramid_long", "open_long"])
        result = self.compare(
            "aggressive", signals, positions, 2,
            {"SOL": 2, "AVAX": 0},
        )
        self.assertEqual(result, [])

    def test_invalid_or_untrusted_strategy_inputs_hold(self):
        good = view()
        bad_cases = [
            dict(bot="unknown"), dict(max_positions=True),
            dict(signals={"WRONG": {"action": "buy", "bull_conf": 0.9}}),
            dict(signals={"SOL-USD": {"action": "buy",
                                    "bull_conf": float("nan")}}),
            dict(signals={"SOL-USD": {"action": "hold_long",
                                    "osc": float("inf")}}, bot="intraday"),
            dict(signals={"SOL-USD": {"action": "buy", "osc": 0.4,
                                    "pyramid_added": 1}}, bot="aggressive"),
            dict(pyramid_state={"SOL": 3}, bot="aggressive"),
            dict(pyramid_state={"SOL": 1}),
            dict(account_view=view(equity="5")),
        ]
        for changes in bad_cases:
            args = dict(bot="daily", signals={}, account_view=good,
                        max_positions=2, pyramid_state=None)
            args.update(changes)
            with self.subTest(changes=str(changes)[:100]):
                r = inspect_pure_strategy_decisions_offline(**args)
                self.assertEqual(r.state, "HOLD")
                self.assertFalse(r.local_decisions_compared)
                self.assertEqual(r.proposed_actions, ())

    def test_module_has_no_order_or_network_dependencies(self):
        module = ROOT / "sender_review/pure_strategy_decisions_offline.py"
        names = set()
        for n in ast.walk(ast.parse(module.read_text("utf-8"))):
            if isinstance(n, ast.Import):
                names.update(a.name for a in n.names)
            if isinstance(n, ast.ImportFrom):
                names.add(n.module)
        self.assertEqual(names, {
            "dataclasses", "math",
            "sender_review.signer_free_account_view_offline",
        })


if __name__ == "__main__":
    unittest.main()
