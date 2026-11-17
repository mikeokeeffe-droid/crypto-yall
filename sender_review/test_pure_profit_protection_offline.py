"""Offline-only, non-executable parity checks for profit-protection triggers."""
import ast
from pathlib import Path
import unittest

from sender_review.pure_profit_protection_offline import (
    SyntheticProtectionRules, inspect_pure_profit_protection_offline,
)
from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)


def account(*positions):
    state = {
        "marginSummary": {"accountValue": "100"},
        "assetPositions": [
            {"position": {
                "coin": coin, "szi": str(size), "entryPx": str(entry_px),
                "unrealizedPnl": str(pnl),
                "leverage": {"type": "cross", "value": lev},
            }}
            for coin, size, entry_px, pnl, lev in positions
        ],
    }
    result = extract_signer_free_account_view_offline(user_state=state)
    assert result.fixture_parsed, result.reason
    return result


def inspect(bot="intraday", positions=None, peaks=None, **kwargs):
    return inspect_pure_profit_protection_offline(
        bot=bot,
        account_view=positions if positions is not None
                     else account(("SOL", 1, 100, 0.1, 2)),
        peak_returns={} if peaks is None else peaks,
        **kwargs,
    )


class ProfitProtectionOfflineTests(unittest.TestCase):
    def deny(self, result):
        for flag in (
            "exchange_origin_authenticated", "account_scope_verified",
            "position_ownership_verified", "existing_position_protected",
            "reentry_locks_persisted", "effective_reduce_only_verified",
            "runtime_identity_authenticated", "submit_authorized",
            "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, flag), False, flag)

    def test_intraday_small_profit_floor_and_loss_cap_precedence(self):
        sample = account(("SOL", 1, 100, 0.25, 2))
        r = inspect(positions=sample, peaks={"SOL": 1.0})
        self.assertEqual(r.state, "PURE_TRIGGER_FIXTURE_HOLD")
        self.assertEqual(len(r.proposals), 1)
        self.assertEqual(r.proposals[0]["protection_mode"], "SMALL PROFIT FLOOR")
        self.assertEqual(r.proposals[0]["close_size"], 1.0)
        self.assertEqual(r.proposed_lock_marks, (("SOL", "long"),))
        self.deny(r)

        loss = inspect(positions=account(("SOL", -1, 100, -2, 2)),
                       peaks={"SOL": 2.0},
                       rules=SyntheticProtectionRules(loss_cap_usd=1.0))
        self.assertEqual(loss.proposals[0]["protection_mode"], "USD LOSS CAP")
        self.assertEqual(loss.proposals[0]["side"], "short")
        self.deny(loss)

    def test_intraday_trailing_and_no_trigger(self):
        trigger = inspect(positions=account(("SOL", 1, 100, -0.5, 2)),
                          peaks={"SOL": 2.0})
        self.assertEqual(trigger.proposals[0]["protection_mode"],
                         "TRAILING PROFIT PROTECTION")
        self.assertAlmostEqual(trigger.proposals[0]["protection_giveback_pct"], 2.5)
        self.deny(trigger)
        inactive = inspect(positions=account(("SOL", 1, 100, 0.8, 2)),
                           peaks={"SOL": 0.9})
        self.assertEqual(inactive.proposals, ())
        self.deny(inactive)

    def test_aggressive_high_low_leverage_bands(self):
        high = inspect(bot="aggressive",
                       positions=account(("SOL", 1, 100, 0.5, 3)),
                       peaks={"SOL": 1.6})
        self.assertEqual(high.proposals[0]["protection_mode"],
                         "HIGH LEVERAGE TRAILING PROFIT PROTECTION")
        self.assertEqual(high.proposals[0]["protection_arm_pct"], 0.4)
        self.assertEqual(high.proposals[0]["protection_max_giveback_pct"], 1.0)
        self.deny(high)
        low = inspect(bot="aggressive",
                      positions=account(("SOL", 1, 100, 0.5, 2)),
                      peaks={"SOL": 1.6})
        self.assertEqual(low.proposals, ())
        self.deny(low)
        low_trigger = inspect(bot="aggressive",
                              positions=account(("SOL", 1, 100, -0.5, 2)),
                              peaks={"SOL": 1.6})
        self.assertEqual(low_trigger.proposals[0]["protection_mode"],
                         "LOW LEVERAGE TRAILING PROFIT PROTECTION")
        self.deny(low_trigger)

    def test_prior_signal_exit_wins_and_protection_only_discards_entries(self):
        sig_close = {
            "ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
            "side": "long", "close_size": 1.0, "reason": "sell_exit signal",
        }
        r = inspect(positions=account(("SOL", 1, 100, -3, 2)),
                    peaks={"SOL": 3.0}, initial_actions=(sig_close,))
        self.assertEqual(r.proposals, (sig_close,))
        self.assertEqual(r.proposed_lock_marks, ())
        self.deny(r)
        entry = {
            "ticker": "AVAX-USD", "hl_coin": "AVAX", "action": "open_long",
            "side": "long",
        }
        held = inspect(positions=account(("SOL", 1, 100, -3, 2)),
                       peaks={"SOL": 3.0}, initial_actions=(entry, sig_close),
                       protection_only=True)
        self.assertEqual(len(held.proposals), 1)
        self.assertEqual(held.proposals[0]["protection_mode"],
                         "SMALL PROFIT FLOOR")
        self.assertFalse(any(x["action"].startswith("open")
                             for x in held.proposals))
        self.deny(held)
        disabled = inspect(initial_actions=(entry,), enabled=False,
                           protection_only=True)
        self.assertEqual(disabled.proposals, ())
        self.assertEqual(disabled.state, "DISABLED_PROTECTION_FIXTURE_HOLD")
        self.deny(disabled)

    def test_invalid_snapshot_peaks_and_rules_fail_closed(self):
        cases = (
            {"bot": "daily"},
            {"peak_returns": {"SOL": float("nan")}},
            {"peak_returns": {"WRONG": 2.0}},
            {"rules": SyntheticProtectionRules(loss_cap_usd=-1.0)},
            {"rules": SyntheticProtectionRules(aggressive_high_threshold=0.0)},
            {"initial_actions": ({"action": "market_open", "hl_coin": "SOL"},)},
            {"protection_only": 1},
        )
        for changes in cases:
            args = dict(bot="intraday", account_view=account(), peak_returns={})
            args.update(changes)
            with self.subTest(changes=changes):
                result = inspect_pure_profit_protection_offline(**args)
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.local_trigger_reviewable)
                self.deny(result)

    def test_pure_module_cannot_import_signer_or_network(self):
        path = Path(__file__).with_name("pure_profit_protection_offline.py")
        imports = set()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "dataclasses", "math",
            "sender_review.signer_free_account_view_offline",
            "sender_review.pure_strategy_decisions_offline",
        })


if __name__ == "__main__":
    unittest.main()
