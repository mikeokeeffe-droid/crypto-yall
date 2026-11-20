"""Synthetic JSON boundary tests: never connect to an exchange."""
import unittest

from offline_hyperliquid_json_boundary import inspect_json_payload_offline


class JsonBoundaryTests(unittest.TestCase):
    def test_valid_order_json_is_untrusted(self):
        r = inspect_json_payload_offline(
            raw=b'{"status":"unknownOid"}', kind="orderStatus")
        self.assertEqual(r.status, "parsed_untrusted")

    def test_valid_empty_fills_are_untrusted(self):
        r = inspect_json_payload_offline(
            raw=b"[]", kind="userFillsByTime")
        self.assertEqual(r.status, "parsed_untrusted")

    def test_malformed_and_ambiguous_json_holds(self):
        for raw in (
            b"{", b'{"status":"filled","status":"rejected"}',
            b'{"value":NaN}', b'{"value":Infinity}',
            b'{"value":-Infinity}', b"\xff", b"",
            b"{} trailing",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(inspect_json_payload_offline(
                    raw=raw, kind="orderStatus").status, "hold")

    def test_response_shape_mismatch_holds(self):
        self.assertEqual(inspect_json_payload_offline(
            raw=b"[]", kind="orderStatus").status, "hold")
        self.assertEqual(inspect_json_payload_offline(
            raw=b"{}", kind="userFillsByTime").status, "hold")

    def test_size_and_type_limits_hold(self):
        self.assertEqual(inspect_json_payload_offline(
            raw=b"[] ", kind="userFillsByTime", max_bytes=2).status, "hold")
        self.assertEqual(inspect_json_payload_offline(
            raw="[]", kind="userFillsByTime").status, "hold")
        self.assertEqual(inspect_json_payload_offline(
            raw=b"[]", kind="exchange").status, "hold")


if __name__ == "__main__":
    unittest.main()
