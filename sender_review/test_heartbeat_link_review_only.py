"""Offline-only, synthetic heartbeat protocol regression tests."""
import json
import unittest

from sender_review.heartbeat_link_review_only import (
    HeartbeatObserver, HeartbeatReceiver, HeartbeatRejected, create_probe,
)

KEY = b"frozen-test-only-key-never-deploy-" * 2
OTHER_KEY = b"wrong-test-only-key-never-deploy" * 2
BOOT = "a" * 32
NONCE = "b" * 32


def probe(seq=1, nonce=NONCE, now=200):
    return create_probe(key=KEY, boot=BOOT, seq=seq, nonce=nonce, now=now)


class HeartbeatLinkReviewTests(unittest.TestCase):
    def test_fresh_ack_round_trip_and_health_timeout(self):
        receiver = HeartbeatReceiver(key=KEY)
        observer = HeartbeatObserver(key=KEY, timeout_seconds=6, max_rtt_seconds=2)
        request = probe()
        reply = receiver.receive(probe=request, now=200)
        verdict = observer.acknowledge(
            probe=request, ack=reply, now=200,
            sent_monotonic=10.0, recv_monotonic=10.08,
        )
        self.assertTrue(verdict.connected)
        self.assertEqual(verdict.last_rtt_ms, 80)
        self.assertTrue(observer.status(now_monotonic=15.9).connected)
        expired = observer.status(now_monotonic=16.09)
        self.assertFalse(expired.connected)
        self.assertEqual(expired.reason, "heartbeat timeout")

    def test_replay_reorder_and_duplicate_session_rejected(self):
        receiver = HeartbeatReceiver(key=KEY)
        receiver.receive(probe=probe(2), now=200)
        for sample in (probe(2), probe(1)):
            with self.assertRaises(HeartbeatRejected):
                receiver.receive(probe=sample, now=200)
        receiver.receive(probe=probe(3), now=200)

    def test_signed_probe_and_ack_tampering_rejected(self):
        receiver = HeartbeatReceiver(key=KEY)
        observer = HeartbeatObserver(key=KEY)
        original = probe()
        for name, value in (("seq", 2), ("nonce", "c" * 32),
                            ("sent", 201), ("boot", "c" * 32)):
            payload = json.loads(original)
            payload[name] = value
            with self.subTest(name=name), self.assertRaises(HeartbeatRejected):
                receiver.receive(
                    probe=json.dumps(payload).encode(), now=200,
                )
        signed_ack = receiver.receive(probe=original, now=200)
        forged = json.loads(signed_ack)
        forged["recv"] = 201
        with self.assertRaises(HeartbeatRejected):
            observer.acknowledge(
                probe=original, ack=json.dumps(forged).encode(), now=200,
                sent_monotonic=5, recv_monotonic=5.1,
            )
        with self.assertRaises(HeartbeatRejected):
            HeartbeatReceiver(key=OTHER_KEY).receive(probe=original, now=200)
        with self.assertRaises(HeartbeatRejected):
            HeartbeatObserver(key=OTHER_KEY).acknowledge(
                probe=original, ack=signed_ack, now=200,
                sent_monotonic=5, recv_monotonic=5.1,
            )

    def test_stale_slow_missing_wrong_ack_rejected(self):
        request = probe()
        receiver = HeartbeatReceiver(key=KEY)
        with self.assertRaisesRegex(HeartbeatRejected, "stale"):
            receiver.receive(probe=request, now=220)
        reply = receiver.receive(probe=request, now=200)
        for ack, sent, received in (
            (reply, 1, 4),
            (reply, 4, 3),
            (b"", 1, 1.1),
        ):
            with self.subTest(ack=ack[:10], sent=sent), self.assertRaises(HeartbeatRejected):
                HeartbeatObserver(key=KEY).acknowledge(
                    probe=request, ack=ack, now=200,
                    sent_monotonic=sent, recv_monotonic=received,
                )
        with self.assertRaisesRegex(HeartbeatRejected, "wrong acknowledgement"):
            HeartbeatObserver(key=KEY).acknowledge(
                probe=probe(2), ack=reply, now=200,
                sent_monotonic=1, recv_monotonic=1.1,
            )

    def test_unknown_fields_duplicate_keys_and_trade_requests_denied(self):
        receiver = HeartbeatReceiver(key=KEY)
        request = probe()
        self.assertRaises(HeartbeatRejected, receiver.receive,
                          probe=b'{"v":1,"v":1}', now=200)
        for extra in (
            {"action": "market_close"},
            {"submit_authorized": True},
            {"kind": "trade"},
        ):
            payload = {**json.loads(request), **extra}
            with self.subTest(extra=extra), self.assertRaises(HeartbeatRejected):
                receiver.receive(probe=json.dumps(payload).encode(), now=200)
        for invalid in (b"x" * 513, b"[]", b"{}", b"not json"):
            with self.assertRaises(HeartbeatRejected):
                receiver.receive(probe=invalid, now=200)

    def test_new_boot_does_not_silently_reset_observer(self):
        receiver = HeartbeatReceiver(key=KEY)
        observer = HeartbeatObserver(key=KEY)
        p1 = probe()
        a1 = receiver.receive(probe=p1, now=200)
        observer.acknowledge(probe=p1, ack=a1, now=200,
                             sent_monotonic=1, recv_monotonic=1.1)
        p2 = create_probe(key=KEY, boot="c" * 32,
                          seq=1, nonce="d" * 32, now=201)
        a2 = receiver.receive(probe=p2, now=201)
        with self.assertRaisesRegex(HeartbeatRejected, "boot change"):
            observer.acknowledge(probe=p2, ack=a2, now=201,
                                 sent_monotonic=2, recv_monotonic=2.1)

    def test_key_is_mandatory_and_no_orders_are_possible(self):
        with self.assertRaises(HeartbeatRejected):
            HeartbeatReceiver(key=b"short")
        self.assertFalse(hasattr(HeartbeatReceiver, "place_order"))
        self.assertFalse(hasattr(HeartbeatObserver, "close_position"))
        self.assertFalse(HeartbeatObserver(key=KEY).status(now_monotonic=0).connected)


if __name__ == "__main__":
    unittest.main()
