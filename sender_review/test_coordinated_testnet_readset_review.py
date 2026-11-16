"""No HTTP/DB/exchange: regressions for coordinated six-frame HOLD."""
import unittest

from sender_review.coordinated_testnet_readset_review import (
    inspect_coordinated_readset_offline,
)


def sample():
    position = {"assetPositions": [
        {"position": {"coin": "SOL", "szi": "0.20"}},
    ]}
    order = {"status": "filled", "order": {
        "oid": 123, "coin": "SOL", "side": "B",
        "origSz": "0.20", "timestamp": 1200,
    }}
    fill = {"oid": 123, "tid": 456, "coin": "SOL", "side": "B",
            "sz": "0.20", "time": 1300}
    return {
        "positions_before": position, "open_orders_before": [],
        "historical_orders": [order], "user_fills": [fill],
        "open_orders_after": [], "positions_after": position,
        "start_time_ms": 1000, "end_time_ms": 2000,
    }


class CoordinatedReadsetReviewTests(unittest.TestCase):
    def assert_never_authorized(self, r):
        for key in (
            "network_performed", "exchange_origin_authenticated",
            "account_scope_verified", "history_complete",
            "from_flat_baseline_verified", "bot_position_ownership_verified",
            "durable_fence_reserved", "submit_authorized",
            "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(r, key), False, key)

    def test_coherent_six_frames_still_hold(self):
        result = inspect_coordinated_readset_offline(**sample())
        self.assertTrue(result.locally_consistent)
        self.assertEqual(result.state, "COHERENT_SIX_FRAME_FIXTURE_HOLD")
        self.assertEqual(result.observed_position_count, 1)
        self.assertEqual(result.reviewed_order_count, 1)
        self.assertEqual(result.reviewed_fill_count, 1)
        self.assertEqual(len(result.observed_positions_sha256), 64)
        self.assert_never_authorized(result)

    def test_changed_positions_open_orders_or_history_hold(self):
        scenarios = (
            {"positions_after": {"assetPositions": [
                {"position": {"coin": "SOL", "szi": "0.21"}}
            ]}},
            {"open_orders_before": [{
                "oid": 10, "coin": "SOL", "side": "B", "sz": "0.10",
            }]},
            {"open_orders_after": [{
                "oid": 10, "coin": "SOL", "side": "B", "sz": "0.10",
            }]},
            {"historical_orders": []},
            {"user_fills": []},
            {"historical_orders": [{
                "status": "filled", "order": {
                    "oid": 123, "coin": "SOL", "side": "B",
                    "origSz": "0.30", "timestamp": 1200,
                },
            }]},
            {"historical_orders": [{
                "status": "filled", "order": {
                    "oid": 123, "coin": "SOL", "side": "A",
                    "origSz": "0.20", "timestamp": 1200,
                },
            }]},
            {"start_time_ms": 1301},
            {"end_time_ms": 1200},
        )
        for change in scenarios:
            with self.subTest(change=change):
                args = sample()
                args.update(change)
                result = inspect_coordinated_readset_offline(**args)
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.locally_consistent)
                self.assert_never_authorized(result)

    def test_malformed_input_cannot_claim_coherence(self):
        for field, value in (
            ("positions_before", {"assetPositions": "bad"}),
            ("positions_after", None),
            ("open_orders_before", {}),
            ("open_orders_after", [False]),
            ("historical_orders", "malformed"),
            ("user_fills", [{"oid": 123}]),
            ("start_time_ms", True),
            ("end_time_ms", 9007199254740992),
        ):
            with self.subTest(field=field):
                args = sample()
                args[field] = value
                result = inspect_coordinated_readset_offline(**args)
                self.assertEqual(result.state, "HOLD")
                self.assert_never_authorized(result)


if __name__ == "__main__":
    unittest.main()
