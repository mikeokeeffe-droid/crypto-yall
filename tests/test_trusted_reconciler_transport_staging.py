import unittest
from trusted_reconciler_transport_staging import TrustedRpcTransport

class FakeResponse:
    status = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, count): return self.body[:count]

class TransportTests(unittest.TestCase):
    def test_reject_http(self):
        with self.assertRaises(ValueError):
            TrustedRpcTransport("http://localhost", "token")
    def test_reject_missing_token(self):
        with self.assertRaises(ValueError):
            TrustedRpcTransport("https://example.test", "")
    def test_reject_endpoint_with_embedded_credentials(self):
        for endpoint in ("https://user:pass@example.test", "https://example.test?key=secret",
                         "https://example.test/#token", "https://"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    TrustedRpcTransport(endpoint, "dedicated")

    def test_reject_whitespace_credentials(self):
        for token in (" ", "bad token", "bad\\ntoken", "\\ttoken"):
            with self.subTest(token=repr(token)):
                with self.assertRaises(ValueError):
                    TrustedRpcTransport("https://example.test", token)

    def test_disallowed_rpc_does_not_open_network(self):
        calls = []
        client = TrustedRpcTransport("https://example.test", "dedicated",
                                    opener=lambda *a, **k: calls.append(a))
        with self.assertRaises(ValueError):
            client("resolve_bot_entry_intent", {})
        self.assertEqual(calls, [])

    def test_allowlisted_rpc(self):
        seen = []
        def opener(request, timeout):
            seen.append((request.full_url, request.get_header("Authorization"), timeout))
            return FakeResponse(b"true")
        client = TrustedRpcTransport("https://example.test", "dedicated", opener=opener)
        self.assertTrue(client("record_bot_position_owner", {"p_coin": "SOL"}))
        self.assertEqual(seen[0][1], "Bearer dedicated")
        self.assertEqual(seen[0][2], 10)
    def test_reject_unlisted_rpc(self):
        client = TrustedRpcTransport("https://example.test", "dedicated")
        with self.assertRaises(ValueError):
            client("delete_everything", {})
    def test_fail_closed_ambiguous_response(self):
        client = TrustedRpcTransport("https://example.test", "dedicated",
                                    opener=lambda *args, **kwargs: FakeResponse(b'{"data":true}'))
        self.assertFalse(client("mark_bot_position_closed", {}))

if __name__ == "__main__":
    unittest.main()
