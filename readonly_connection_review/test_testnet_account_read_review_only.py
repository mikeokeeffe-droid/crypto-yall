"""Offline-only fixtures for the standalone Testnet account checker."""
import json
import unittest
from unittest.mock import patch
from readonly_connection_review import testnet_account_read_review_only as reader


class FakeResponse:
    def __init__(self, data, *, status=200, length=None):
        self.status = status
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.length = length

    def getheader(self, name):
        if name == "Content-Length":
            return self.length
        return None

    def read(self, limit):
        return self.data[:limit]


class FakeConn:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.closed = False

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    def getresponse(self):
        return self.reply

    def close(self):
        self.closed = True


class ReadOnlyAccountTests(unittest.TestCase):
    def test_only_two_fixed_info_types(self):
        for name in ("clearinghouseState", "openOrders"):
            body = json.loads(reader.body_for(name))
            self.assertEqual(body["user"], reader.WALLET)
            self.assertEqual(body["type"], name)
            self.assertEqual(body["dex"], "")
        for name in ("exchange", "order", "userFills", "historicalOrders", "/exchange"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                reader.body_for(name)

    def test_fixed_path_no_signing_and_strict_response(self):
        for kind, response, expected in (
            ("clearinghouseState", {"assetPositions": []}, 0),
            ("openOrders", [{"oid": 4}, {"oid": 5}], 2),
        ):
            conn = FakeConn(FakeResponse(response))
            count = reader.fetch_info(kind, connection_factory=lambda: conn)
            self.assertEqual(count, expected)
            self.assertTrue(conn.closed)
            args, kwargs = conn.calls[0]
            self.assertEqual(args[:2], ("POST", "/info"))
            self.assertEqual(json.loads(kwargs["body"])["type"], kind)
            self.assertNotIn("Authorization", kwargs["headers"])

    def test_rejects_non200_and_malformed_or_large_response(self):
        for response in (
            FakeResponse([], status=403),
            FakeResponse([], length=str(reader.MAX_RESPONSE_BYTES + 1)),
            FakeResponse(b"{not-json"),
            FakeResponse(b"x" * (reader.MAX_RESPONSE_BYTES + 1)),
            FakeResponse({"wrong": []}),
        ):
            conn = FakeConn(response)
            with self.subTest(response=response), self.assertRaises(ValueError):
                reader.fetch_info("clearinghouseState", connection_factory=lambda: conn)
            self.assertTrue(conn.closed)

    def test_requires_explicit_manual_flag_without_io(self):
        with patch.object(reader, "fetch_info") as fetch:
            self.assertEqual(reader.main([]), 2)
            fetch.assert_not_called()

    def test_two_queries_only_after_manual_flag(self):
        with patch.object(reader, "fetch_info", side_effect=[0, 0]) as fetch:
            self.assertEqual(reader.main(["--manual-review-only"]), 0)
            self.assertEqual([call.args[0] for call in fetch.call_args_list],
                             ["clearinghouseState", "openOrders"])


if __name__ == "__main__":
    unittest.main()
