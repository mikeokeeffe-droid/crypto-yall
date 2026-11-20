"""Inert SSH stdio heartbeat validation. No SSH calls, no network, no trades."""
import json
import unittest
from sender_review.ssh_heartbeat_stdio_review_only import (
    InvalidHeartbeat, make_review_ack,
)


class SshHeartbeatStdioReviewOnlyTests(unittest.TestCase):
    def setUp(self):
        self.now = 1800000000
        self.payload = {"v": 1, "kind": "heartbeat",
                        "nonce": "a" * 32, "sent": self.now}

    def frame(self, **changes):
        return json.dumps({**self.payload, **changes}).encode("ascii")

    def test_valid_challenge_receives_non_authorizing_ack(self):
        result = json.loads(make_review_ack(self.frame(), now=self.now,
                                            random_hex="b" * 32))
        self.assertEqual(result, {"v": 1, "kind": "heartbeat_ack",
                                  "nonce": "a" * 32, "server_nonce": "b" * 32,
                                  "received": self.now, "authority": "none"})

    def test_rejects_stale_future_wrong_kind_and_trade_fields(self):
        for value in (
            self.frame(sent=self.now - 11),
            self.frame(sent=self.now + 11),
            self.frame(kind="entry"),
            self.frame(action="market_close"),
            self.frame(submit_authorized=True),
            self.frame(nonce="wrong"),
            self.frame(v=True),
            b'{"v":1,"v":1,"kind":"heartbeat","nonce":"' +
              b"a" * 32 + b'","sent":1800000000}',
            b"{}", b"", b"[]" , b"X" * 385,
        ):
            with self.subTest(raw=value[:50]), self.assertRaises(InvalidHeartbeat):
                make_review_ack(value, now=self.now, random_hex="b" * 32)

    def test_invalid_server_challenge_is_rejected(self):
        with self.assertRaises(InvalidHeartbeat):
            make_review_ack(self.frame(), now=self.now, random_hex="notrandom")


if __name__ == "__main__":
    unittest.main()
