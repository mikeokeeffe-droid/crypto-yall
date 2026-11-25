"""Offline tests for fixed HTTPS transport adapter; no real network allowed."""
import copy
import json
import unittest

from readonly_connection_review import testnet_account_read_review_only as reader
from readonly_connection_review.https_gateway_transport_review import (
    review_fixed_info_transport,
)
from readonly_connection_review.testnet_egress_policy_review_offline import (
    PolicyHold, load_review_contract,
)
from readonly_connection_review.test_testnet_account_read_review_only import FakeConn, FakeResponse
from readonly_connection_review.test_testnet_egress_policy_review_offline import safe_frames


class HttpsGatewayTransportReviewTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_review_contract()
        self.frames = safe_frames()

    def test_no_default_network_transport_available(self):
        with self.assertRaises(PolicyHold):
            review_fixed_info_transport(self.frames, policy=self.policy)

    def test_only_two_fixed_info_requests_with_fake_connections(self):
        connections = [
            FakeConn(FakeResponse({"assetPositions": [{"position": {}}]})),
            FakeConn(FakeResponse([{"oid": 123}, {"oid": 456}])),
        ]
        calls = []

        def fake_factory():
            calls.append(1)
            return connections[len(calls) - 1]

        actual = review_fixed_info_transport(
            self.frames, policy=self.policy, connection_factory=fake_factory
        )
        self.assertEqual(actual, {"positions": 1, "open_orders": 2})
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(conn.closed for conn in connections))
        for conn, kind in zip(connections, ("clearinghouseState", "openOrders")):
            args, kwargs = conn.calls[0]
            self.assertEqual(args[:2], ("POST", "/info"))
            self.assertEqual(json.loads(kwargs["body"]), {
                "type": kind, "user": reader.WALLET, "dex": ""
            })

    def test_unapproved_frame_rejected_before_connecting(self):
        for key, value in (("host", "api.hyperliquid.xyz"),
                           ("path", "/exchange"), ("method", "GET")):
            frames = copy.deepcopy(self.frames)
            frames[0][key] = value
            count = []
            def fake_factory():
                count.append(1)
                raise AssertionError("must not touch network")
            with self.subTest(key=key), self.assertRaises(PolicyHold):
                review_fixed_info_transport(
                    frames, policy=self.policy, connection_factory=fake_factory
                )
            self.assertEqual(count, [])

    def test_network_authority_flag_rejected(self):
        changed = dict(self.policy, network_authorized=True)
        with self.assertRaises(PolicyHold):
            review_fixed_info_transport(
                self.frames, policy=changed, connection_factory=lambda: None
            )

    def test_second_response_error_fails_without_retry(self):
        connections = [
            FakeConn(FakeResponse({"assetPositions": []})),
            FakeConn(FakeResponse([], status=403)),
        ]
        count = []
        def factory():
            count.append(1)
            return connections[len(count) - 1]
        with self.assertRaises(ValueError):
            review_fixed_info_transport(
                self.frames, policy=self.policy, connection_factory=factory
            )
        self.assertEqual(len(count), 2)
        self.assertTrue(all(conn.closed for conn in connections))


if __name__ == "__main__":
    unittest.main()
