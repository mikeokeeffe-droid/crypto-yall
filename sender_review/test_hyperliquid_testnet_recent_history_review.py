"""No testnet transport; validate bounded fake history only."""
import unittest

from sender_review import hyperliquid_testnet_recent_history_review as r


def orders():
    return [{"status": "filled", "order": {"oid": 123, "coin": "SOL",
             "side": "B", "origSz": "0.20", "timestamp": 1200}}]


def fills():
    return [{"oid": 123, "tid": 456, "coin": "SOL",
             "side": "B", "sz": "0.20", "time": 1300}]


class RecentHistoryOfflineTests(unittest.TestCase):
    def no_auth(self, result):
        for key in (
            "historical_completeness_verified", "baseline_from_flat_verified",
            "account_ownership_verified", "bot_position_ownership_verified",
            "close_authorized", "retry_authorized", "submit_authorized",
            "signing_enabled",
        ):
            self.assertFalse(getattr(result, key), key)

    def test_entrypoint_cannot_enable_network(self):
        for flag in (True, False, 1, "true", None):
            result = r.inspect_testnet_recent_history_review(
                configured_public_account="0x" + "1" * 40,
                start_time_ms=1000, end_time_ms=2000,
                enabled_readonly_testnet_network=flag,
            )
            self.assertEqual(result.state, "HOLD")
            self.assertFalse(result.recent_records_consistent)
            self.no_auth(result)
        self.assertFalse(hasattr(r, "urllib"))
        self.assertFalse(hasattr(r, "_info_query"))

    def test_matching_fake_fills_still_hold(self):
        result = r.inspect_recent_history_documents_offline(
            historical_document=orders(), fills_document=fills(),
            start_time_ms=1000, end_time_ms=2000,
        )
        self.assertEqual(result.state, "RECENT_TESTNET_HISTORY_REVIEW_ONLY_HOLD")
        self.assertTrue(result.recent_records_consistent)
        self.assertTrue(result.possibly_truncated)
        self.assertEqual(result.recent_order_count, 1)
        self.assertEqual(result.recent_fill_count, 1)
        self.no_auth(result)

    def test_partial_missing_or_mismatched_history_denied(self):
        scenarios = (
            ([], fills()), (orders(), []),
            (orders(), [dict(fills()[0], oid=999)]),
            (orders(), [dict(fills()[0], sz="0.1")]),
            (orders(), [dict(fills()[0], time=999)]),
            (orders() * 2, fills()),
        )
        for order_data, fill_data in scenarios:
            with self.subTest(orders=order_data, fills=fill_data):
                result = r.inspect_recent_history_documents_offline(
                    historical_document=order_data, fills_document=fill_data,
                    start_time_ms=1000, end_time_ms=2000,
                )
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.recent_records_consistent)
                self.no_auth(result)

    def test_out_of_bounds_window_denied(self):
        for start, end in ((True, 2000), (2000, 1000),
                           (1000, 1000 + 86400001)):
            result = r.inspect_recent_history_documents_offline(
                historical_document=orders(), fills_document=fills(),
                start_time_ms=start, end_time_ms=end,
            )
            self.assertEqual(result.state, "HOLD")
            self.no_auth(result)


if __name__ == "__main__":
    unittest.main()
