"""No-network synthetic leverage, notional, stale-observation safety tests."""
import json
import unittest
from sender_review.pre_submit_leverage_risk_review_offline import (
    inspect_pre_submit_risk_fixture_offline,
)

NOW = 1700000002000
BODY = json.dumps({
    "version": 1, "action": "open_long", "side": "long", "coin": "SOL",
    "rounded_size": "0.25", "requested_leverage": 2,
    "request_nonce": "a"*32,
}, sort_keys=True, separators=(",", ":")).encode("ascii")


def review(**changes):
    args = dict(
        body=BODY, update_outcome="confirmed_fixture", observed_leverage=2,
        market_price="100", max_notional="30",
        sample_time_ms=NOW - 1000, fixture_now_ms=NOW,
    )
    args.update(changes)
    return inspect_pre_submit_risk_fixture_offline(**args)


class OfflinePreSubmitRiskTests(unittest.TestCase):
    def assert_denies_authority(self, record):
        self.assertEqual(record.state, "HOLD")
        for flag in (
            "effective_leverage_authenticated", "market_price_authenticated",
            "scope_authenticated", "durable_fence_reserved",
            "risk_budget_authorized", "order_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(record, flag), False, flag)

    def test_bounded_synthetic_arithmetic_still_never_permits_order(self):
        r = review()
        self.assertTrue(r.synthetic_arithmetic_consistent)
        self.assertEqual(r.computed_notional, "25.00")
        self.assertEqual(r.requested_leverage, 2)
        self.assert_denies_authority(r)

    def test_failed_unknown_mismatched_or_stale_leverage_holds(self):
        for change in (
            {"update_outcome": "failed"}, {"update_outcome": "timeout"},
            {"update_outcome": "unknown"}, {"update_outcome": ""},
            {"update_outcome": True}, {"observed_leverage": 3},
            {"observed_leverage": True}, {"observed_leverage": 1},
            {"sample_time_ms": NOW - 5001},
            {"sample_time_ms": NOW + 1},
            {"sample_time_ms": True},
            {"fixture_now_ms": True},
        ):
            with self.subTest(change=change):
                r = review(**change)
                self.assert_denies_authority(r)
                self.assertFalse(r.synthetic_arithmetic_consistent)

    def test_invalid_notional_quantity_and_risk_cap_hold(self):
        for change in (
            {"market_price": "0"}, {"market_price": "-1"},
            {"market_price": "NaN"}, {"market_price": "Infinity"},
            {"market_price": "100.000000001"},
            {"market_price": 100},
            {"max_notional": "24.99"}, {"max_notional": "0"},
            {"max_notional": None}, {"max_notional": "1e8"},
            {"body": BODY.replace(b'"rounded_size":"0.25"', b'"rounded_size":"0"')},
            {"body": BODY.replace(b'"requested_leverage":2', b'"requested_leverage":3')},
            {"body": b'{"action":"exchange"}'},
        ):
            with self.subTest(change=change):
                r = review(**change)
                self.assert_denies_authority(r)
                self.assertFalse(r.synthetic_arithmetic_consistent)

    def test_legacy_aggressive_minimum_order_inflation_exceeds_allocation(self):
        # Existing aggressive_executor.py testnet branch raises a small
        # proposed order to $12, but has no equivalent of Intraday's
        # max_notional=capital*leverage guard before market_open.
        # Preserve the old code untouched; new sender must reject the
        # actual size after any minimum-notional adjustment.
        inflated = json.loads(BODY)
        inflated["rounded_size"] = "0.12"  # $12.00 at synthetic $100/coin
        wire = json.dumps(inflated, sort_keys=True,
                          separators=(",", ":")).encode("ascii")
        for cap in ("3", "5", "11.99"):
            with self.subTest(approved_cap=cap):
                r = review(body=wire, market_price="100", max_notional=cap)
                self.assert_denies_authority(r)
                self.assertFalse(r.synthetic_arithmetic_consistent)
                self.assertIn("exceeds fixture cap", r.reason)
        r = review(body=wire, market_price="100", max_notional="12")
        self.assertTrue(r.synthetic_arithmetic_consistent)
        self.assert_denies_authority(r)  # Matching fixture is NEVER approval.

    def test_does_not_import_exchange_or_signer(self):
        import ast
        from pathlib import Path
        src = Path(__file__).with_name(
            "pre_submit_leverage_risk_review_offline.py").read_text("utf-8")
        modules = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                modules.update(x.name for x in node.names)
            if isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {
            "dataclasses", "decimal", "json", "re",
            "sender_review.request_contract",
        })


if __name__ == "__main__":
    unittest.main()
