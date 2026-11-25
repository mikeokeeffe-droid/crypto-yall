"""Differential parity against AST-isolated original profit-protection wrappers.

Only extract named PURE decision functions from pinned original source files;
never IMPORT either executable bot or wrapper, call its main(), run network,
load credentials, mutate a journal, or issue an order. Mock the externally
stateful lock helpers and original signal-decider, so this proves ONLY the
profit-trigger/action-record subset. Every new implementation result HOLDs.
"""
import ast
import datetime as dt
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)
from sender_review.pure_profit_protection_offline import (
    SyntheticProtectionRules, inspect_pure_profit_protection_offline,
)
from sender_review.pure_strategy_decisions_offline import TICKER_TO_COIN

ROOT = Path(__file__).resolve().parents[1]
LEGACY = {
    "intraday": ("intraday_profit_protection.py",
                 ("_protected_decide_trades",)),
    "aggressive": ("aggressive_profit_protection.py",
                   ("_current_return_pct", "decide_trades")),
}
RULES = SyntheticProtectionRules(loss_cap_usd=2.0)


def fixture_view(rows):
    raw = {
        "marginSummary": {"accountValue": "100"},
        "assetPositions": [{
            "position": {
                "coin": coin, "szi": str(sz),
                "entryPx": str(entry), "unrealizedPnl": str(pnl),
                "leverage": {"type": "cross", "value": lev},
            }
        } for coin, sz, entry, pnl, lev in rows],
    }
    review = extract_signer_free_account_view_offline(user_state=raw)
    assert review.fixture_parsed, review.reason
    return review


def legacy_trigger_decisions(bot, *, view, peaks, initial_actions,
                             protection_only, enabled, rules):
    """Extract only named AST function definitions and stub side effects."""
    filename, names = LEGACY[bot]
    nodes = ast.parse((ROOT / filename).read_text(encoding="utf-8")).body
    selected = [n for n in nodes
                if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == set(names)
    marks = []
    namespace = {
        "dt": dt,
        "base": SimpleNamespace(HL_SYMBOL_MAP=dict(TICKER_TO_COIN)),
        "HL_SYMBOL_MAP": dict(TICKER_TO_COIN),
        "_state": {"peak_return_pct": dict(peaks)},
        "_peak_returns": dict(peaks),
        "ARM_PCT": rules.intraday_arm,
        "GIVEBACK_PCT": rules.intraday_giveback,
        "LOW_LEV_ARM_PCT": rules.aggressive_low_arm,
        "LOW_LEV_GIVEBACK_PCT": rules.aggressive_low_giveback,
        "HIGH_LEV_ARM_PCT": rules.aggressive_high_arm,
        "HIGH_LEV_GIVEBACK_PCT": rules.aggressive_high_giveback,
        "HIGH_LEV_THRESHOLD": rules.aggressive_high_threshold,
        "SMALL_PROFIT_PEAK_PCT": rules.small_profit_peak,
        "SMALL_PROFIT_FLOOR_PCT": rules.small_profit_floor,
        "LOSS_CAP_USD": rules.loss_cap_usd,
        "ENABLED": enabled,
        "PROTECTION_ONLY": protection_only,
        "LOCK_REVIEW_AFTER_HOURS": 2,
        "REENTRY_COOLDOWN_MINUTES": 15,
        "_original_decide_trades": lambda *args: [dict(x) for x in initial_actions],
        "refresh_locks": lambda *args, **kwargs: {},
        "block_locked_entries": lambda actions, *args, **kwargs: actions,
        "mark_pending_lock": lambda _state, coin, side: marks.append((coin, side)),
        "loss_cap_breached": (
            lambda pnl, cap: cap > 0 and pnl <= -cap
        ),
        "print": lambda *args, **kwargs: None,
    }
    compiled = compile(ast.fix_missing_locations(
        ast.Module(body=selected, type_ignores=[])), filename, "exec")
    exec(compiled, namespace)
    if bot == "intraday":
        fn = namespace["_protected_decide_trades"]
        actions = fn({}, view.positions, 3)
    else:
        fn = namespace["decide_trades"]
        actions = fn({}, view.positions, 3, {})
    return actions, tuple(marks)


def signal_close(coin="SOL", side="long"):
    return {
        "ticker": next(t for t, c in TICKER_TO_COIN.items() if c == coin),
        "hl_coin": coin, "action": "close", "side": side,
        "close_size": 1.0, "reason": "original signal exit",
    }


def entry(coin="AVAX"):
    return {
        "ticker": next(t for t, c in TICKER_TO_COIN.items() if c == coin),
        "hl_coin": coin, "action": "open_long", "side": "long",
        "reason": "original entry proposal",
    }


class ProfitProtectionLegacyParityTests(unittest.TestCase):
    def compare(self, bot, rows, peaks, actions=(), *,
                protection_only=False, enabled=True, rules=RULES):
        view = fixture_view(rows)
        original_actions, original_marks = legacy_trigger_decisions(
            bot, view=view, peaks=peaks, initial_actions=actions,
            protection_only=protection_only, enabled=enabled, rules=rules,
        )
        pure = inspect_pure_profit_protection_offline(
            bot=bot, account_view=view, peak_returns=dict(peaks),
            initial_actions=tuple(actions), protection_only=protection_only,
            enabled=enabled, rules=rules,
        )
        self.assertTrue(pure.local_trigger_reviewable, pure.reason)
        self.assertEqual(pure.state, "PURE_TRIGGER_FIXTURE_HOLD"
                         if enabled else "DISABLED_PROTECTION_FIXTURE_HOLD")
        self.assertEqual(list(pure.proposals), original_actions)
        self.assertEqual(pure.proposed_lock_marks, original_marks)
        for name in (
            "exchange_origin_authenticated", "account_scope_verified",
            "position_ownership_verified", "existing_position_protected",
            "reentry_locks_persisted", "effective_reduce_only_verified",
            "runtime_identity_authenticated", "submit_authorized",
            "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(pure, name), False, name)
        return pure

    def test_intraday_original_floor_trailing_loss_cap_and_no_trigger(self):
        rows_and_peaks = (
            ([("SOL", 1, 100, 0.25, 2)], {"SOL": 1.0}),
            ([("SOL", 1, 100, -1.2, 2)], {"SOL": 0.9}),
            ([("SOL", -1, 100, -3, 2)], {"SOL": 3.0}),
            ([("SOL", 1, 100, 0.8, 2)], {"SOL": 0.9}),
        )
        for rows, peaks in rows_and_peaks:
            with self.subTest(rows=rows, peaks=peaks):
                self.compare("intraday", rows, peaks)

    def test_aggressive_original_high_low_trailing_and_floor(self):
        cases = (
            ([("SOL", 1, 100, 0.5, 3)], {"SOL": 1.6}),
            ([("SOL", 1, 100, -1.2, 2)], {"SOL": 0.9}),
            ([("SOL", -1, 100, 0.25, 2)], {"SOL": 1.0}),
            ([("SOL", 1, 100, 0.5, 2)], {"SOL": 1.6}),
        )
        for rows, peaks in cases:
            with self.subTest(rows=rows, peaks=peaks):
                self.compare("aggressive", rows, peaks)

    def test_both_original_wrappers_signal_close_precedes_profit_exit(self):
        for bot in LEGACY:
            with self.subTest(bot=bot):
                result = self.compare(
                    bot, [("SOL", 1, 100, -4, 3)], {"SOL": 3},
                    actions=(signal_close(), entry()),
                )
                self.assertEqual(result.proposals[0]["reason"],
                                 "original signal exit")
                self.assertEqual(result.proposed_lock_marks, ())

    def test_both_original_wrappers_protection_only_blocks_new_entries(self):
        for bot in LEGACY:
            with self.subTest(bot=bot):
                result = self.compare(
                    bot, [("SOL", 1, 100, -4, 3)], {"SOL": 3},
                    actions=(signal_close(), entry()), protection_only=True,
                )
                self.assertEqual(len(result.proposals), 1)
                self.assertEqual(result.proposals[0]["action"], "close")
                self.assertEqual(result.proposed_lock_marks, (("SOL", "long"),))

    def test_both_original_wrappers_disabled_protection_does_not_trust(self):
        for bot in LEGACY:
            with self.subTest(bot=bot):
                self.compare(
                    bot, [("SOL", 1, 100, -4, 3)], {"SOL": 3},
                    actions=(entry(),), enabled=False,
                )
                self.compare(
                    bot, [("SOL", 1, 100, -4, 3)], {"SOL": 3},
                    actions=(entry(),), enabled=False, protection_only=True,
                )

    def test_multi_coin_includes_short_close_and_does_not_import_live_code(self):
        for bot in LEGACY:
            with self.subTest(bot=bot):
                result = self.compare(
                    bot, [
                        ("SOL", 1, 100, -4, 3),
                        ("AVAX", -1, 100, 0.25, 2),
                        ("LINK", 1, 100, 0.5, 2),
                    ],
                    {"SOL": 3, "AVAX": 1.0, "LINK": 0.8},
                )
                self.assertEqual([x["hl_coin"] for x in result.proposals],
                                 ["SOL", "AVAX"])
                self.assertEqual(result.proposed_lock_marks,
                                 (("SOL", "long"), ("AVAX", "short")))
        for forbidden in (
            "hyperliquid_executor", "intraday_executor",
            "aggressive_executor", "intraday_profit_protection",
            "aggressive_profit_protection", "hyperliquid.exchange",
            "eth_account",
        ):
            self.assertNotIn(forbidden, sys.modules)


if __name__ == "__main__":
    unittest.main()
