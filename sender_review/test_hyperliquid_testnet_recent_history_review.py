"""All transport mocked: bounded testnet recent history remains HOLD."""
import io
import json
import unittest
from unittest.mock import patch

from sender_review import hyperliquid_testnet_recent_history_review as review
from sender_review import hyperliquid_testnet_readonly_snapshot_review as transport

ACCOUNT = "0x" + "1" * 40
START = 1000
END = 2000


class Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, value):
        self.data = io.BytesIO(json.dumps(value).encode())

    def geturl(self):
        return transport._URL

    def read(self, length):
        return self.data.read(length)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(),
                           json.loads(request.data)))
        return self.responses.pop(0)


def orders():
    return [{"status": "filled", "order": {
        "oid": 123, "coin": "SOL", "side": "B",
        "origSz": "0.20", "timestamp": 1200,
    }}]


def fills():
    return [{"oid": 123, "tid": 456, "coin": "SOL", "side": "B",
             "sz": "0.20", "time": 1300}]


class RecentHistoryTests(unittest.TestCase):
    def inspect(self, docs=None, **kwargs):
        if docs is None:
            docs = [orders(), fills()]
        fake = FakeOpener([Response(d) for d in docs])
        with patch.object(review.urllib.request, "build_opener",
                          return_value=fake):
            result = review.inspect_testnet_recent_history_review(
                configured_public_account=ACCOUNT, start_time_ms=START,
                end_time_ms=END, enabled_readonly_testnet_network=True,
                **kwargs,
            )
        return result, fake

    def no_authority(self, result):
        self.assertEqual(result.state in (
            "HOLD", "RECENT_TESTNET_HISTORY_REVIEW_ONLY_HOLD"), True)
        for name in ("historical_completeness_verified",
                     "baseline_from_flat_verified",
                     "account_ownership_verified",
                     "bot_position_ownership_verified", "close_authorized",
                     "retry_authorized", "submit_authorized", "signing_enabled"):
            self.assertFalse(getattr(result, name), name)
        self.assertTrue(result.possibly_truncated)

    def test_default_is_off_with_no_network(self):
        with patch.object(review.urllib.request, "build_opener",
                          side_effect=AssertionError("must not open network")):
            for enabled in (False, None, 1, "yes"):
                with self.subTest(enabled=enabled):
                    result = review.inspect_testnet_recent_history_review(
                        configured_public_account=ACCOUNT, start_time_ms=START,
                        end_time_ms=END,
                        enabled_readonly_testnet_network=enabled,
                    )
                    self.assertEqual(result.state, "HOLD")
                    self.no_authority(result)

    def test_two_exact_testnet_info_queries_with_no_signer(self):
        result, fake = self.inspect()
        self.assertEqual(result.state,
                         "RECENT_TESTNET_HISTORY_REVIEW_ONLY_HOLD")
        self.assertTrue(result.recent_records_consistent)
        self.assertEqual((result.recent_order_count, result.recent_fill_count),
                         (1, 1))
        self.assertEqual(len(fake.calls), 2)
        for url, method, data in fake.calls:
            self.assertEqual(url, transport._URL)
            self.assertEqual(method, "POST")
            self.assertEqual(data["user"], ACCOUNT)
            self.assertNotIn("private_key", data)
        self.assertEqual(fake.calls[0][2]["type"], "historicalOrders")
        self.assertEqual(fake.calls[1][2], {
            "type": "userFillsByTime", "user": ACCOUNT,
            "startTime": START, "endTime": END,
            "aggregateByTime": False,
        })
        self.no_authority(result)

    def test_missing_conflicting_or_repeated_records_hold(self):
        cases = (
            [[], fills()],
            [orders(), [dict(fills()[0], oid=999)]],
            [orders(), [dict(fills()[0], coin="AVAX")]],
            [orders(), [dict(fills()[0], side="A")]],
            [orders(), fills() * 2],
            [orders() * 2, fills()],
            [[dict(orders()[0], status="open")], fills()],
            [orders(), [dict(fills()[0], time=999)]],
            [orders(), [dict(fills()[0], sz="NaN")]],
            [orders() * 2000, fills()],
            [orders(), fills() * 2000],
        )
        for docs in cases:
            with self.subTest(docs=str(docs)[:100]):
                result, _ = self.inspect(docs)
                self.assertEqual(result.state, "HOLD")
                self.assertFalse(result.recent_records_consistent)
                self.no_authority(result)

    def test_invalid_scope_never_fetches(self):
        with patch.object(review.urllib.request, "build_opener",
                          side_effect=AssertionError("no network")):
            for account, start, end in (
                ("bad", START, END),
                (ACCOUNT, True, END),
                (ACCOUNT, END, START),
                (ACCOUNT, START, START + 86400001),
            ):
                with self.subTest(account=account, start=start, end=end):
                    result = review.inspect_testnet_recent_history_review(
                        configured_public_account=account,
                        start_time_ms=start, end_time_ms=end,
                        enabled_readonly_testnet_network=True,
                    )
                    self.assertEqual(result.state, "HOLD")
                    self.no_authority(result)


if __name__ == "__main__":
    unittest.main()
