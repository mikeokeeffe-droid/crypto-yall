"""Offline snapshot validation and hard-denial regression tests."""
import unittest

from sender_review import hyperliquid_testnet_readonly_snapshot_review as r


class SnapshotOfflineTests(unittest.TestCase):
    def test_transport_always_hold_and_authority_denied(self):
        for flag in (True, False, None, "true", 1):
            for account in ("0x" + "1" * 40, "bad", None):
                with self.subTest(flag=flag, account=account):
                    result = r.inspect_testnet_info_readonly_snapshot(
                        configured_public_account=account,
                        enabled_readonly_testnet_network=flag,
                    )
                    self.assertEqual(result.state, "HOLD")
                    self.assertFalse(result.snapshot_consistent)
                    self.assertEqual(result.observed_positions, ())
                    for field in (
                        "account_ownership_verified", "historical_completeness_verified",
                        "fills_reconciled", "position_ownership_verified",
                        "runtime_identity_authenticated", "replay_consumed",
                        "journal_recorded", "submit_authorized", "close_authorized",
                        "signing_enabled",
                    ):
                        self.assertFalse(getattr(result, field), field)

    def test_offline_positions_normalize_decimal(self):
        payload = {"assetPositions": [
            {"position": {"coin": "SOL", "szi": "0.20"}},
            {"position": {"coin": "AVAX", "szi": "-0.30"}},
        ]}
        self.assertEqual(r._positions(payload), {"SOL": "0.2", "AVAX": "-0.3"})
        payload["assetPositions"].reverse()
        self.assertEqual(r._positions(payload), {"AVAX": "-0.3", "SOL": "0.2"})

    def test_offline_positions_reject_invalid(self):
        bad = (
            {"assetPositions": "no"},
            {"assetPositions": [{"position": {"coin": "SOL", "szi": "NaN"}}]},
            {"assetPositions": [{"position": {"coin": "SOL", "szi": "0"}}]},
            {"assetPositions": [{"position": {"coin": "SOL", "szi": "0.2"}},
                                 {"position": {"coin": "SOL", "szi": "0.3"}}]},
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                r._positions(value)

    def test_offline_open_orders_are_never_execution_authority(self):
        orders = [{"oid": 1, "coin": "SOL", "side": "B", "sz": "0.20"}]
        self.assertEqual(r._orders(orders), {1: ("SOL", "B", "0.2")})
        for invalid in ([orders[0], orders[0]], [{"oid": 1, "coin": "SOL",
                                                 "side": "B", "sz": "-0.1"}],
                        [{"oid": True, "coin": "SOL", "side": "B", "sz": "1"}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                r._orders(invalid)

    def test_no_reachable_http_helpers_remain(self):
        self.assertFalse(hasattr(r, "_info_query"))
        self.assertFalse(hasattr(r, "_NoRedirect"))
        self.assertFalse(hasattr(r, "urllib"))


if __name__ == "__main__":
    unittest.main()
