"""P3 shared-coin three-bot netting tests: every outcome must HOLD."""
import ast
from dataclasses import replace
from pathlib import Path
import unittest

from sender_review.shared_account_reconciliation_offline import (
    SyntheticAccountPosition, SyntheticBotAllocation, SyntheticFill,
    SyntheticNettingReview, review_synthetic_account_netting_offline,
)

ACCOUNT = "0x" + "1" * 40
COIN = "SOL"
FILL = "0x" + "a" * 32
CLOID = "0x" + "b" * 32


def exchange(**changes):
    return replace(SyntheticAccountPosition(
        ACCOUNT, COIN, "0.30", "0.36"), **changes)


def bots(**overrides):
    base = (
        SyntheticBotAllocation("daily", ACCOUNT, COIN, "0.10", "0.16"),
        SyntheticBotAllocation("intraday", ACCOUNT, COIN, "0.10", "0.10"),
        SyntheticBotAllocation("aggressive", ACCOUNT, COIN, "0.10", "0.10"),
    )
    return tuple(replace(x, **overrides.get(x.bot, {})) for x in base)


def fills(**changes):
    return (replace(SyntheticFill(
        FILL, "daily", ACCOUNT, COIN, CLOID, "0.06"), **changes),)


def assess(**changes):
    params = dict(exchange=exchange(), bots=bots(), fills=fills(),
                  expected_account=ACCOUNT, expected_coin=COIN)
    params.update(changes)
    return review_synthetic_account_netting_offline(**params)


class SharedAccountOfflineTests(unittest.TestCase):
    def assert_hold(self, result):
        self.assertIs(type(result), SyntheticNettingReview)
        self.assertEqual(result.state, "HOLD")
        for field in (
            "trusted_exchange_position", "trusted_fill_history",
            "bot_ownership_verified", "account_lock_verified",
            "retry_authorized", "protective_close_authorized",
            "fence_release_authorized", "submit_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, field), False, field)

    def test_matched_three_bot_figures_are_never_trusted(self):
        result = assess()
        self.assertEqual(result.reason,
                         "synthetic-figures-match-but-exchange-provenance-unverified")
        self.assertTrue(result.synthetic_arithmetic_consistent)
        self.assert_hold(result)

    def test_unattributed_exchange_pre_and_post_positions_hold(self):
        cases = (
            (dict(exchange=exchange(before_signed="0.31")),
             "exchange-before-not-attributed"),
            (dict(exchange=exchange(after_signed="0.37")),
             "exchange-fill-arithmetic-mismatch"),
            (dict(bots=bots(daily={"after_signed": "0.15"})),
             "bot-fill-arithmetic-mismatch"),
            (dict(bots=bots(intraday={"before_signed": "0.11",
                                      "after_signed": "0.11"})),
             "exchange-before-not-attributed"),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason):
                r = assess(**changes)
                self.assertEqual(r.reason, reason)
                self.assert_hold(r)

    def test_shared_coin_opposing_claims_do_not_expose_false_flatness(self):
        # Two bots may claim positions canceling to zero exchange net.
        # An exchange-net zero MUST NOT mean either bot is safely flat.
        claimed = (
            SyntheticBotAllocation("daily", ACCOUNT, COIN, "0.50", "0.50"),
            SyntheticBotAllocation("intraday", ACCOUNT, COIN, "-0.50", "-0.50"),
            SyntheticBotAllocation("aggressive", ACCOUNT, COIN, "0", "0"),
        )
        r = assess(exchange=exchange(before_signed="0", after_signed="0"),
                   bots=claimed, fills=(SyntheticFill(FILL, "aggressive",
                        ACCOUNT, COIN, CLOID, "0.01"),
                        SyntheticFill("0x" + "c" * 32, "aggressive",
                        ACCOUNT, COIN, "0x" + "d" * 32, "-0.01")))
        self.assertEqual(r.reason, "shared-coin-offsetting-claims-unattributable")
        self.assert_hold(r)

    def test_duplicate_or_cross_account_fill_provenance_holds(self):
        for fx in (
            fills()[0],
            replace(fills()[0], account="0x" + "2" * 40),
            replace(fills()[0], coin="AVAX"),
            replace(fills()[0], bot="unknown"),
            replace(fills()[0], cloid="not-an-id"),
            replace(fills()[0], fill_id="not-an-id"),
        ):
            with self.subTest(fx=fx):
                variant = (fills()[0], fx) if fx == fills()[0] else (fx,)
                r = assess(fills=variant)
                self.assertEqual(r.reason, "unverified-or-duplicate-fill-provenance")
                self.assert_hold(r)

    def test_missing_bots_fills_and_fake_types_hold(self):
        scenarios = (
            dict(bots=bots()[:2]), dict(bots=bots() + bots()[:1]),
            dict(bots=bots(daily={"bot": "intraday"})),
            dict(fills=()), dict(fills=None),
            dict(exchange=None), dict(exchange={"before_signed": "0.30"}),
            dict(bots=list(bots())), dict(fills=list(fills())),
            dict(expected_account="0x" + "2" * 40),
            dict(expected_coin="AVAX"), dict(expected_coin=None),
        )
        for changes in scenarios:
            with self.subTest(changes=changes):
                self.assert_hold(assess(**changes))

    def test_malformed_numbers_and_zero_fill_hold(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e-3",
                      "0.123456789", "1000001", None, 1, " 0.3"):
            with self.subTest(value=value):
                self.assert_hold(assess(exchange=exchange(after_signed=value)))
                self.assert_hold(assess(fills=fills(signed_delta=value)))
        self.assertEqual(assess(fills=fills(signed_delta="0")).reason,
                         "invalid-fill-quantity")

    def test_module_imports_have_no_transport_db_or_signer(self):
        source = Path(__file__).with_name(
            "shared_account_reconciliation_offline.py").read_text("utf-8")
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {"dataclasses", "decimal", "re"})


if __name__ == "__main__":
    unittest.main()
