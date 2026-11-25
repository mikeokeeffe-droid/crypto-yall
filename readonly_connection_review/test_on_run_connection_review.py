"""Offline verification of what the one-shot Testnet connection will do at run time.

All network interactions here are replaced with local fake connections.
No mainnet, signing, trading, wallet access, or network request.
"""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from readonly_connection_review import testnet_account_read_review_only as checker
from readonly_connection_review.test_testnet_account_read_review_only import FakeConn, FakeResponse


class OnRunConnectionReview(unittest.TestCase):
    def test_default_connection_has_exact_testnet_host_tls_and_short_timeout(self):
        conn = FakeConn(FakeResponse([]))
        sentinel = object()
        with patch.object(checker.ssl, "create_default_context", return_value=sentinel) as tls, \
             patch.object(checker.http.client, "HTTPSConnection", return_value=conn) as https:
            self.assertEqual(checker.fetch_info("openOrders"), 0)
        tls.assert_called_once_with()
        https.assert_called_once_with(checker.HOST, 443, context=sentinel, timeout=8)
        args, kwargs = conn.calls[0]
        self.assertEqual(args, ("POST", "/info"))
        self.assertEqual(kwargs["headers"]["Connection"], "close")
        self.assertEqual(json.loads(kwargs["body"])["user"], checker.WALLET)
        self.assertTrue(conn.closed)

    def test_run_prints_only_counts_after_exact_two_successful_calls(self):
        called = []
        def response(kind):
            called.append(kind)
            return 0 if kind == "clearinghouseState" else 0
        out = io.StringIO()
        with patch.object(checker, "fetch_info", side_effect=response), contextlib.redirect_stdout(out):
            self.assertEqual(checker.main(["--manual-review-only"]), 0)
        self.assertEqual(called, ["clearinghouseState", "openOrders"])
        self.assertEqual(out.getvalue().strip(),
                         "TESTNET READ ONLY: positions=0; open_orders=0; no trade authority")

    def test_connection_failure_holds_without_second_request_or_leaking_error(self):
        err = io.StringIO()
        with patch.object(checker, "fetch_info", side_effect=OSError("SECRET-MUST-NOT-PRINT")) as fetch, \
             contextlib.redirect_stderr(err):
            self.assertEqual(checker.main(["--manual-review-only"]), 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("SECRET-MUST-NOT-PRINT", err.getvalue())
        self.assertIn("HOLD:", err.getvalue())

    def test_no_manual_approval_no_calls(self):
        with patch.object(checker, "fetch_info") as fetch, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([]), 2)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
