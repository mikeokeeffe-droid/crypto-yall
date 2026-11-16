"""Strictly mocked testnet /info snapshot transport: zero real networking."""
import io
import json
import unittest
from unittest.mock import patch

from sender_review import hyperliquid_testnet_readonly_snapshot_review as read

ACCOUNT = "0x" + "1" * 40


class Response:
    def __init__(self, body, *, status=200, url=read._URL, content_type="application/json"):
        self.data = io.BytesIO(body)
        self.status = status
        self.url = url
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url

    def read(self, n):
        return self.data.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(), request.data, timeout))
        return self.responses.pop(0)


def body(value):
    return json.dumps(value, separators=(",", ":")).encode()


def positions(size="0.20"):
    return {"assetPositions": [{"position": {"coin": "SOL", "szi": size}}]}


def orders():
    return [{"oid": 123, "coin": "SOL", "side": "B", "sz": "0.10"}]


class ReadonlySnapshotTests(unittest.TestCase):
    def check(self, responses=None):
        if responses is None:
            responses = [Response(body(positions())), Response(body(orders())),
                         Response(body(positions()))]
        fake = FakeOpener(responses)
        with patch.object(read.urllib.request, "build_opener", return_value=fake):
            answer = read.inspect_testnet_info_readonly_snapshot(
                configured_public_account=ACCOUNT, enabled_readonly_testnet_network=True,
            )
        return answer, fake

    def deny_authority(self, result):
        for name in (
            "account_ownership_verified", "historical_completeness_verified",
            "fills_reconciled", "position_ownership_verified",
            "runtime_identity_authenticated", "replay_consumed",
            "journal_recorded", "submit_authorized", "close_authorized",
            "signing_enabled",
        ):
            self.assertFalse(getattr(result, name), name)

    def test_default_never_attempts_network(self):
        with patch.object(read.urllib.request, "build_opener",
                          side_effect=AssertionError("network unavailable")):
            for enabled in (False, None, "yes", 1):
                with self.subTest(enabled=enabled):
                    r = read.inspect_testnet_info_readonly_snapshot(
                        configured_public_account=ACCOUNT,
                        enabled_readonly_testnet_network=enabled,
                    )
                    self.assertEqual(r.state, "HOLD")
                    self.deny_authority(r)

    def test_three_exact_readonly_requests_always_hold(self):
        result, fake = self.check()
        self.assertEqual(result.state, "OBSERVED_TESTNET_READONLY_HOLD")
        self.assertTrue(result.snapshot_consistent)
        self.assertEqual(result.position_count, 1)
        self.assertEqual(result.open_order_count, 1)
        self.assertEqual(len(result.positions_digest), 64)
        self.assertEqual(len(fake.calls), 3)
        for index, (url, method, data, timeout) in enumerate(fake.calls):
            self.assertEqual(url, read._URL)
            self.assertEqual(method, "POST")
            self.assertEqual(timeout, 5)
            request = json.loads(data)
            self.assertEqual(request, {
                "type": "openOrders" if index == 1 else "clearinghouseState",
                "user": ACCOUNT, "dex": "",
            })
        self.deny_authority(result)

    def test_position_changed_between_reads_stays_hold(self):
        result, fake = self.check([
            Response(body(positions("0.20"))), Response(body([])),
            Response(body(positions("0.30"))),
        ])
        self.assertFalse(result.snapshot_consistent)
        self.assertEqual(len(fake.calls), 3)
        self.deny_authority(result)

    def test_malformed_and_bad_http_response_refused(self):
        responses = [
            Response(b'{"assetPositions":[],"assetPositions":[]}'),
            Response(b'{"assetPositions":NaN}'),
            Response(b"not json"),
            Response(b"x" * (read._LIMIT + 1)),
            Response(body(positions()), status=500),
            Response(body(positions()), url="https://evil.invalid/info"),
            Response(body(positions()), content_type="text/html"),
            Response(body({"assetPositions": [
                {"position": {"coin": "SOL", "szi": "0.2"}},
                {"position": {"coin": "SOL", "szi": "0.3"}},
            ]})),
            Response(body(positions("NaN"))),
        ]
        for bad in responses:
            with self.subTest(case=bad.status, raw=bad.data.getvalue()[:30]):
                result, fake = self.check([bad])
                self.assertEqual(result.state, "HOLD")
                self.deny_authority(result)

    def test_untrusted_account_and_duplicate_orders_fail_closed(self):
        for account in (None, "0x" + "g" * 40, "0x" + "2" * 39, True):
            with self.subTest(account=account), patch.object(
                read.urllib.request, "build_opener",
                side_effect=AssertionError("network unavailable"),
            ):
                result = read.inspect_testnet_info_readonly_snapshot(
                    configured_public_account=account,
                    enabled_readonly_testnet_network=True,
                )
                self.assertEqual(result.state, "HOLD")
        duplicate = orders() * 2
        result, _ = self.check([
            Response(body(positions())), Response(body(duplicate)),
        ])
        self.assertEqual(result.state, "HOLD")
        self.deny_authority(result)


if __name__ == "__main__":
    unittest.main()
