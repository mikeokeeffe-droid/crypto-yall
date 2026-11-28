"""All fixtures are synthetic: no network or real TLS validation."""
import unittest

from offline_hyperliquid_http_envelope import (
    inspect_http_envelope_offline, MAX_RESPONSE_BYTES, MAX_ELAPSED_MS,
)

URL = "https://api.hyperliquid.xyz/info"


def inspect(**changes):
    args = dict(status_code=200, elapsed_ms=100, body_bytes=1000,
                redirect_count=0, tls_verified=True, expected_url=URL,
                final_url=URL, network_error=None,
                content_type="application/json")
    args.update(changes)
    return inspect_http_envelope_offline(**args)


class HttpEnvelopeTests(unittest.TestCase):
    def test_normal_synthetic_envelope_only_review(self):
        result = inspect()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_timeout_error_and_rate_limit_hold(self):
        for changes in (
            {"network_error": "timeout"}, {"status_code": 429},
            {"status_code": 500}, {"status_code": 302},
            {"elapsed_ms": MAX_ELAPSED_MS + 1},
            {"elapsed_ms": -1},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(inspect(**changes).status, "hold")

    def test_oversized_or_unbounded_body_holds(self):
        for n in (-1, MAX_RESPONSE_BYTES + 1, None, True):
            with self.subTest(n=n):
                self.assertEqual(inspect(body_bytes=n).status, "hold")

    def test_redirect_tls_and_origin_mismatch_hold(self):
        for changes in (
            {"redirect_count": 1},
            {"tls_verified": False},
            {"tls_verified": "true"},
            {"final_url": "https://evil.example/info"},
            {"expected_url": "https://evil.example/info",
             "final_url": "https://evil.example/info"},
            {"content_type": "text/html"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(inspect(**changes).status, "hold")

    def test_untrusted_type_fields_hold(self):
        self.assertEqual(inspect(status_code=True).status, "hold")
        self.assertEqual(inspect(redirect_count=False).status, "hold")
        self.assertEqual(inspect(elapsed_ms=True).status, "hold")

    def test_no_transport_in_module(self):
        import offline_hyperliquid_http_envelope as module
        self.assertFalse(hasattr(module, "request"))
        self.assertFalse(hasattr(module, "post"))


if __name__ == "__main__":
    unittest.main()
