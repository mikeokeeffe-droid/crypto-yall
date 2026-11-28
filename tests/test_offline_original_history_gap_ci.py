"""Legacy history helpers under denied synthetic exchange-history reads.

A missing fill list is not an observed empty fill history. A zero-valued
funding fallback is explicitly incomplete. The accompanying review ALWAYS
returns HOLD and cannot approve a close, position ownership or dispatch.
"""
from pathlib import Path
import sys
import tempfile
import unittest

from offline_original_history_gap_ci import (
    extract_original_history_helpers_offline,
    review_legacy_history_accounting_offline,
)
from offline_signer_free_read_bootstrap_ci import (
    bootstrap_original_read_only_offline,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40


def denied_info():
    view = bootstrap_original_read_only_offline(
        verified_bot="daily",
        pinned_environment="testnet", pinned_account=ACCOUNT,
        snapshot={
            "environment": "testnet", "account": ACCOUNT,
            "user_state": {
                "marginSummary": {"accountValue": "150"},
                "assetPositions": [],
            },
            "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
            "all_mids": {"SOL": "125"},
            "meta": {"universe": [{"name": "SOL", "szDecimals": 3}]},
        },
    )
    if view is None:
        raise AssertionError("synthetic signer-free view unavailable")
    return view.info


class OriginalHistoryGapTests(unittest.TestCase):
    def test_denied_order_fills_do_not_establish_zero_exchange_fills(self):
        helpers = extract_original_history_helpers_offline(source_root=ROOT)
        totals = helpers["get_order_fill_totals"](
            denied_info(), ACCOUNT, 12345, "SOL", attempts=1,
        )
        self.assertIsNone(totals)
        review = review_legacy_history_accounting_offline(
            fill_totals=totals,
            funding_totals={
                "funding_pnl": 0.0,
                "funding_count": 0,
                "funding_data_complete": False,
                "funding_start_time_ms": 1000,
            },
        )
        self.assertEqual(review.state, "hold")
        self.assertFalse(review.fill_details_present)
        self.assertFalse(review.history_complete)
        self.assertFalse(review.ownership_verified)
        self.assertFalse(review.close_authorized)
        self.assertFalse(review.submit_authorized)

    def test_denied_funding_is_zero_valued_but_explicitly_incomplete(self):
        helpers = extract_original_history_helpers_offline(source_root=ROOT)
        # Pinned legacy start time avoids treating an arbitrary local clock
        # fallback as an actual exchange fill timestamp.
        legacy_state = {"position_opened_at_ms": {"SOL": 1000}}
        result = helpers["get_position_funding"](
            legacy_state, denied_info(), ACCOUNT, "SOL", end_time_ms=2000,
        )
        self.assertEqual(result, {
            "funding_pnl": 0.0,
            "funding_count": 0,
            "funding_data_complete": False,
            "funding_start_time_ms": 1000,
        })
        review = review_legacy_history_accounting_offline(
            fill_totals=None, funding_totals=result,
        )
        self.assertFalse(review.funding_reported_complete)
        self.assertFalse(review.ownership_verified)
        self.assertFalse(review.close_authorized)
        self.assertEqual(review.state, "hold")

    def test_missing_start_time_does_not_claim_complete_history(self):
        helpers = extract_original_history_helpers_offline(source_root=ROOT)
        result = helpers["get_position_funding"](
            {}, denied_info(), ACCOUNT, "SOL", end_time_ms=2000,
        )
        self.assertEqual(result["funding_data_complete"], False)
        self.assertIsNone(result["funding_start_time_ms"])
        self.assertEqual(
            review_legacy_history_accounting_offline(
                fill_totals=None, funding_totals=result,
            ).state, "hold",
        )

    def test_forged_complete_legacy_accounting_still_no_authority(self):
        review = review_legacy_history_accounting_offline(
            fill_totals={
                "closed_pnl": 1.2, "fee": 0.2, "fee_tokens": ["USDC"],
                "fill_count": 1, "first_time": 1000, "last_time": 1000,
            },
            funding_totals={
                "funding_pnl": 0.3, "funding_count": 1,
                "funding_data_complete": True, "funding_start_time_ms": 900,
            },
        )
        self.assertEqual(review.state, "hold")
        self.assertTrue(review.fill_details_present)
        self.assertTrue(review.funding_reported_complete)
        self.assertFalse(review.exchange_origin_authenticated)
        self.assertFalse(review.history_complete)
        self.assertFalse(review.ownership_verified)
        self.assertFalse(review.close_authorized)

    def test_new_order_history_mutation_method_is_rejected(self):
        original = (ROOT / "hyperliquid_executor.py").read_text("utf-8")
        changed = original.replace(
            "fills = info.user_fills(address)",
            "fills = info.market_close(address)",
            1,
        )
        self.assertNotEqual(changed, original)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "hyperliquid_executor.py").write_text(
                changed, encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                extract_original_history_helpers_offline(
                    source_root=Path(directory),
                )

    def test_no_original_or_signer_modules_imported(self):
        extract_original_history_helpers_offline(source_root=ROOT)
        for module in (
            "hyperliquid_executor", "intraday_executor",
            "aggressive_executor", "eth_account", "hyperliquid.exchange",
        ):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
