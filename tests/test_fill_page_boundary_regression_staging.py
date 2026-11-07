"""Fail-closed regression for ambiguous Hyperliquid timestamp pagination."""
import unittest
from hyperliquid_fill_pagination_staging import fetch_fills_window

ADDRESS = "0x" + "a" * 40

class Exchange:
    def __init__(self, page):
        self.page = page
        self.calls = 0

    def user_fills_by_time(self, address, start, end):
        self.calls += 1
        return self.page

class PaginationSafetyTests(unittest.TestCase):
    def test_full_page_with_unique_last_timestamp_is_still_ambiguous(self):
        exchange = Exchange([
            {"time": 100, "tid": 1},
            {"time": 101, "tid": 2},
        ])
        result = fetch_fills_window(exchange, ADDRESS, 100, 200, page_limit=2)
        self.assertFalse(result.complete)
        self.assertEqual(result.fills, [])
        self.assertIn("lossless cursor", result.reason)
        self.assertEqual(exchange.calls, 1)

    def test_partial_page_is_complete(self):
        exchange = Exchange([{"time": 100, "tid": 1}])
        result = fetch_fills_window(exchange, ADDRESS, 100, 200, page_limit=2)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.fills), 1)

if __name__ == "__main__":
    unittest.main()
