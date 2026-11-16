"""Offline-only six-frame contract tests. No network, signer, host or keys."""
import hashlib
import json
import unittest
from unittest.mock import patch

from collector_review import six_frame_request_contract_offline as contract
from collector_review import testnet_info_https as existing

ACCOUNT = "0x" + "1" * 40
START = 1700000000000
END = START + 3600000


class SixFrameContractReviewTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertEqual(result.state, "HOLD")
        for name in (
            "network_performed", "origin_authenticated", "history_complete",
            "position_ownership_verified", "request_authorized",
            "order_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, name), False, name)

    def test_exact_ordered_canonical_bodies_and_digest(self):
        result = contract.plan_synthetic_six_frame_readset_offline(
            account=ACCOUNT, start_ms=START, end_ms=END)
        self.assert_no_authority(result)
        self.assertTrue(result.matches_fixture)
        self.assertEqual(len(result.frames), 6)
        expected_kinds = (
            "clearinghouseState", "openOrders", "historicalOrders",
            "userFillsByTime", "openOrders", "clearinghouseState",
        )
        for idx, frame in enumerate(result.frames, 1):
            with self.subTest(step=idx):
                self.assertEqual(frame.step, idx)
                self.assertEqual(frame.kind, expected_kinds[idx - 1])
                self.assertEqual(frame.method, "POST")
                self.assertEqual(frame.path, "/info")
                self.assertEqual(frame.body_sha256, hashlib.sha256(frame.body).hexdigest())
                parsed = json.loads(frame.body)
                self.assertEqual(parsed["type"], frame.kind)
                self.assertEqual(parsed["user"], ACCOUNT)
                self.assertEqual(
                    frame.body, json.dumps(parsed, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode("ascii"))
                self.assertEqual(
                    set(parsed), {"type", "user", "startTime", "endTime",
                                  "aggregateByTime"} if idx == 4 else (
                                  {"type", "user"} if idx == 3 else
                                  {"type", "user", "dex"}))
                self.assertTrue(contract.inspect_synthetic_frame_offline(
                    account=ACCOUNT, start_ms=START, end_ms=END,
                    step=idx, method="POST", path="/info", body=frame.body
                ).matches_fixture)
                self.assert_no_authority(contract.inspect_synthetic_frame_offline(
                    account=ACCOUNT, start_ms=START, end_ms=END,
                    step=idx, method="POST", path="/info", body=frame.body))

    def test_invalid_scope_and_bounded_history_hold(self):
        for account, start, end in (
            ("0x" + "2"*40, START, END),
            (ACCOUNT.upper(), START, END),
            (ACCOUNT, True, END),
            (ACCOUNT, START, False),
            (ACCOUNT, 0, END),
            (ACCOUNT, END, START),
            (ACCOUNT, START, START),
            (ACCOUNT, START, START + 86400001),
            (ACCOUNT, START, 9007199254740992),
            (None, START, END),
        ):
            with self.subTest(account=account, start=start, end=end):
                review = contract.plan_synthetic_six_frame_readset_offline(
                    account=account, start_ms=start, end_ms=end)
                self.assert_no_authority(review)
                self.assertFalse(review.matches_fixture)
                self.assertEqual(review.frames, ())

    def test_wrong_method_path_step_json_or_account_never_matches(self):
        good = contract.plan_synthetic_six_frame_readset_offline(
            account=ACCOUNT, start_ms=START, end_ms=END).frames
        valid = dict(account=ACCOUNT, start_ms=START, end_ms=END,
                     step=4, method="POST", path="/info", body=good[3].body)
        variants = (
            {"step": 0}, {"step": 7}, {"step": True},
            {"method": "GET"}, {"path": "/exchange"},
            {"path": "https://api.hyperliquid.xyz/info"},
            {"body": good[2].body},
            {"body": good[3].body + b" "},
            {"body": b'{"type":"userFillsByTime","user":"0x' + b"1"*40 + b'","startTime":1}'},
            {"body": b'{"type":"exchange"}'},
            {"body": good[3].body.replace(b'false', b'true')},
            {"body": good[3].body.replace(b"1700003600000", b"1700003600001")},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                review = contract.inspect_synthetic_frame_offline(**dict(valid, **variant))
                self.assert_no_authority(review)
                self.assertFalse(review.matches_fixture)

    def test_existing_collector_stays_network_denied(self):
        with patch.object(existing.http.client, "HTTPSConnection") as conn, \\
             patch.object(existing.ssl, "create_default_context") as tls:
            result = existing.collect_testnet_readonly_review(
                account=ACCOUNT, kind="openOrders")
            self.assertEqual(result.state, "hold")
            with self.assertRaises(PermissionError):
                existing._https_post_restricted_review_only(b"{}")
            conn.assert_not_called()
            tls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
