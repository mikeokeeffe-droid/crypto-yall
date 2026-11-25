"""Pure offline review of the proposed Testnet gateway step state machine.

No SSH, API, sockets, filesystem secrets, trading authority or live network.
"""
import copy
import json
import unittest

from readonly_connection_review.offline_gateway_step_gate import (
    OfflineGatewayGate, MAX_LEASE_AGE_SECONDS
)
from readonly_connection_review.testnet_egress_policy_review_offline import (
    FIXED_ACCOUNT, PolicyHold, TYPES, URL
)


NONCE = "0123456789abcdef0123456789abcdef"


class OfflineGatewayStepTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.gate = OfflineGatewayGate(clock=lambda: self.now)

    def start(self):
        self.gate.begin_offline_lease(approval=True, test_nonce=NONCE)

    def test_fixed_two_step_sequence_from_lease_and_spent(self):
        self.assertTrue(self.gate.finished)
        self.start()
        self.assertFalse(self.gate.finished)
        for step, kind in enumerate(TYPES, start=1):
            frame = self.gate.review_step(nonce=NONCE, step=step)
            self.assertEqual(tuple(frame[k] for k in ("scheme", "host", "port", "method", "path")), URL)
            self.assertEqual(json.loads(frame["body"]),
                             {"type": kind, "user": FIXED_ACCOUNT, "dex": ""})
        self.assertTrue(self.gate.finished)
        with self.assertRaises(PolicyHold):
            self.gate.review_step(nonce=NONCE, step=3)

    def test_requires_exact_approval_and_lowercase_nonce(self):
        for approval in (False, None, 1, "yes"):
            gate = OfflineGatewayGate(clock=lambda: self.now)
            with self.subTest(approval=approval), self.assertRaises(PolicyHold):
                gate.begin_offline_lease(approval=approval, test_nonce=NONCE)
        for nonce in ("", "x" * 32, NONCE.upper(), NONCE[:31], NONCE + "0", 12):
            gate = OfflineGatewayGate(clock=lambda: self.now)
            with self.subTest(nonce=nonce), self.assertRaises(PolicyHold):
                gate.begin_offline_lease(approval=True, test_nonce=nonce)

    def test_replay_wrong_nonce_and_duplicate_step_are_rejected(self):
        self.start()
        with self.assertRaises(PolicyHold):
            self.gate.review_step(nonce="0" * 32, step=1)
        self.assertFalse(self.gate.finished)
        self.gate.review_step(nonce=NONCE, step=1)
        with self.assertRaises(PolicyHold):
            self.gate.review_step(nonce=NONCE, step=1)
        self.assertTrue(self.gate.finished)

    def test_lease_expires_fail_closed(self):
        self.start()
        self.now += MAX_LEASE_AGE_SECONDS + 0.01
        with self.assertRaises(PolicyHold):
            self.gate.review_step(nonce=NONCE, step=1)
        self.assertTrue(self.gate.finished)

    def test_caller_supplied_request_is_denied_and_consumes_lease(self):
        self.start()
        for request in (
            {"path": "/exchange"},
            {"host": "api.hyperliquid.xyz"},
            {"type": "order"},
            {"user": "0x" + "0" * 40},
            {},
        ):
            gate = OfflineGatewayGate(clock=lambda: 100.0)
            gate.begin_offline_lease(approval=True, test_nonce=NONCE)
            with self.subTest(request=request), self.assertRaises(PolicyHold):
                gate.review_step(nonce=NONCE, step=1, caller_request=request)
            self.assertTrue(gate.finished)

    def test_boolean_and_zero_step_do_not_bypass_order(self):
        self.start()
        for step in (True, False, 0, 2, "1", 1.0, -1):
            gate = OfflineGatewayGate(clock=lambda: 100.0)
            gate.begin_offline_lease(approval=True, test_nonce=NONCE)
            with self.subTest(step=step), self.assertRaises(PolicyHold):
                gate.review_step(nonce=NONCE, step=step)
            self.assertTrue(gate.finished)

    def test_lease_cannot_be_reopened_on_same_object(self):
        self.start()
        self.gate.review_step(nonce=NONCE, step=1)
        self.gate.review_step(nonce=NONCE, step=2)
        with self.assertRaises(PolicyHold):
            self.gate.begin_offline_lease(approval=True, test_nonce=NONCE)


if __name__ == "__main__":
    unittest.main()
