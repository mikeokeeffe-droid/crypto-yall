"""Offline integration regressions for signer-free three-bot shadow cycle."""
import ast
from pathlib import Path
import unittest

from sender_review.composed_shadow_worker_offline import (
    inspect_shadow_worker_cycle_offline,
)
from sender_review.reentry_lock_transition_review_offline import (
    SyntheticReentryLock,
)


def account(*rows, equity="100"):
    return {
        "marginSummary": {"accountValue": equity},
        "assetPositions": [{"position": {
            "coin": c, "szi": str(size), "entryPx": "100",
            "unrealizedPnl": str(pnl),
            "leverage": {"type": "cross", "value": lev},
        }} for c, size, pnl, lev in rows],
    }


NOW = 1700000000
_UNSET = object()


def shadow(*, bot="intraday", positions=_UNSET, signals=None, **changes):
    args = dict(
        bot=bot,
        user_state=account() if positions is _UNSET else positions,
        signals={} if signals is None else signals,
        max_positions=2, locks=(), synthetic_now_epoch=NOW,
    )
    args.update(changes)
    return inspect_shadow_worker_cycle_offline(**args)


class ComposedShadowWorkerTests(unittest.TestCase):
    def never_authority(self, result):
        for field in (
            "exchange_origin_authenticated", "account_scope_verified",
            "position_ownership_verified", "protective_close_verified",
            "durable_fence_reserved", "request_authorized",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, field), False, field)

    def test_all_three_strategies_in_one_pure_composition(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                signal = {
                    "action": "buy", "bull_conf": 0.7,
                    "osc": 0.7,
                }
                r = shadow(bot=bot, signals={"SOL-USD": signal})
                self.assertTrue(r.review_ready, r.reason)
                self.assertEqual(r.state, "COMPOSED_SYNTHETIC_WORKER_HOLD")
                self.assertEqual(r.close_review_proposals, ())
                self.assertEqual(
                    [(v["action"], v["hl_coin"])
                     for v in r.deferred_entry_proposals],
                    [("open_long", "SOL")],
                )
                self.never_authority(r)

    def test_close_and_same_coin_flip_is_deferred(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                signals = {"SOL-USD": {
                    "action": "buy", "bull_conf": 0.9, "osc": 0.9,
                }}
                r = shadow(
                    bot=bot, positions=account(("SOL", -0.5, 2, 2)),
                    signals=signals, max_positions=1,
                )
                self.assertTrue(r.review_ready, r.reason)
                self.assertEqual(
                    [(p["action"], p["hl_coin"])
                     for p in r.close_review_proposals],
                    [("close", "SOL")],
                )
                self.assertEqual(
                    [(p["action"], p["hl_coin"])
                     for p in r.deferred_entry_proposals],
                    [("open_long", "SOL")],
                )
                self.assertEqual(
                    [(p["action"], p["hl_coin"])
                     for p in r.deferred_flip_entry_proposals],
                    [("open_long", "SOL")],
                )
                self.never_authority(r)

    def test_intraday_profit_protection_close_not_converted_to_order(self):
        r = shadow(
            positions=account(("SOL", 1, -3, 3)),
            signals={"SOL-USD": {"action": "hold_long", "osc": 0.4}},
            peak_returns={"SOL": 3.0},
        )
        self.assertTrue(r.review_ready, r.reason)
        self.assertEqual(len(r.close_review_proposals), 1)
        self.assertEqual(r.close_review_proposals[0]["exit_type"],
                         "PROFIT PROTECTION")
        self.assertEqual(r.possible_pending_lock_marks, (("SOL", "long"),))
        self.never_authority(r)

    def test_protection_only_never_runs_entry(self):
        r = shadow(
            bot="aggressive", protection_only=True,
            positions=account(("SOL", 1, -3, 3)),
            signals={"AVAX-USD": {"action": "buy", "osc": 0.7}},
            peak_returns={"SOL": 3.0},
        )
        self.assertTrue(r.review_ready, r.reason)
        self.assertEqual([p["action"] for p in r.close_review_proposals],
                         ["close"])
        self.assertEqual(r.deferred_entry_proposals, ())
        self.never_authority(r)

    def test_other_bot_lock_blocks_exit_and_entry_proposals(self):
        lock = SyntheticReentryLock(
            bot="aggressive", coin="SOL", side="long",
            nonce="a"*32, fence=1, state="unknown_ack",
            created_epoch=NOW-3600,
        )
        r = shadow(
            bot="intraday", locks=(lock,),
            positions=account(("SOL", 1, 1, 2)),
            signals={"SOL-USD": {"action": "sell_exit"}},
        )
        self.assertTrue(r.review_ready)
        self.assertEqual(r.close_review_proposals, ())
        self.assertEqual(r.reentry_lock_coins, ("SOL",))
        self.assertEqual(r.deferred_entry_proposals, ())
        self.assertEqual([x["action"] for x in r.locked_review_proposals],
                         ["close"])
        self.never_authority(r)

    def test_unknown_external_position_and_disabled_protection_hold(self):
        unknown = shadow(positions=account(("DOGE", 1, 1, 2)),
                         signals={"SOL-USD": {"action": "buy", "osc": 0.8}})
        self.assertEqual(unknown.state, "HOLD")
        self.assertFalse(unknown.review_ready)
        self.never_authority(unknown)
        for bot in ("intraday", "aggressive"):
            with self.subTest(bot=bot):
                disabled = shadow(bot=bot, protection_enabled=False,
                                  signals={"SOL-USD": {"action": "buy", "osc": 0.9}})
                self.assertEqual(disabled.state, "HOLD")
                self.assertFalse(disabled.review_ready)
                self.never_authority(disabled)

    def test_missing_spot_fallback_and_malformed_snapshot_hold(self):
        for sample in (account(equity="5"), {}, None,
                       account(("SOL", 1, 0, 2), equity="NaN")):
            with self.subTest(sample=sample):
                r = shadow(positions=sample)
                self.assertFalse(r.review_ready)
                self.assertEqual(r.state, "HOLD")
                self.never_authority(r)
        r = shadow(positions=account(equity="5"))
        self.assertTrue(r.additional_spot_read_needed)

    def test_malformed_signals_locks_and_daily_protection_only_hold(self):
        lock = SyntheticReentryLock(
            bot="daily", coin="SOL", side="long", nonce="a"*32,
            fence=1, state="unknown_ack", created_epoch=NOW-1,
        )
        cases = (
            {"signals": {"SOL-USD": {"action": "unknown"}}},
            {"signals": {"INVALID": {"action": "buy", "osc": 0.5}}},
            {"locks": (lock, lock)},
            {"protection_only": True, "bot": "daily"},
            {"peak_returns": {"SOL": float("nan")}},
            {"synthetic_now_epoch": -1},
        )
        for changes in cases:
            with self.subTest(changes=str(changes)):
                r = shadow(**changes)
                self.assertFalse(r.review_ready, r.reason)
                self.never_authority(r)

    def test_module_imports_only_pure_offline_dependencies(self):
        filename = Path(__file__).with_name("composed_shadow_worker_offline.py")
        imports = set()
        for node in ast.walk(ast.parse(filename.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses",
            "sender_review.signer_free_account_view_offline",
            "sender_review.pure_strategy_decisions_offline",
            "sender_review.pure_profit_protection_offline",
            "sender_review.reentry_lock_transition_review_offline",
        })


if __name__ == "__main__":
    unittest.main()
