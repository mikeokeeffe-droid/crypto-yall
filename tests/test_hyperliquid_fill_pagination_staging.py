import unittest
from hyperliquid_fill_pagination_staging import fetch_fills_window

ADDR = "0x" + "1" * 40
class Info:
    def __init__(self, pages): self.pages = list(pages)
    def user_fills_by_time(self, address, start, end): return self.pages.pop(0)

class FillPaginationTests(unittest.TestCase):
    def test_short_page_is_complete(self):
        r = fetch_fills_window(Info([[{"time": 100, "tid": 1, "oid": 2}]]), ADDR, 100, 200)
        self.assertTrue(r.complete)
    def test_full_page_then_next_page(self):
        pages = [[{"time": 100, "tid": 1, "oid": 2}, {"time": 101, "tid": 2, "oid": 2}], [{"time": 102, "tid": 3, "oid": 3}]]
        r = fetch_fills_window(Info(pages), ADDR, 100, 200, page_limit=2)
        self.assertTrue(r.complete)
        self.assertEqual(len(r.fills), 3)
    def test_ambiguous_boundary_holds(self):
        page = [{"time": 100, "tid": 1}, {"time": 100, "tid": 2}]
        self.assertFalse(fetch_fills_window(Info([page]), ADDR, 100, 200, page_limit=2).complete)
    def test_duplicate_trade_holds(self):
        page = [{"time": 100, "tid": 1}, {"time": 101, "tid": 1}]
        self.assertFalse(fetch_fills_window(Info([page]), ADDR, 100, 200).complete)
    def test_request_error_holds(self):
        self.assertFalse(fetch_fills_window(Info([]), ADDR, 100, 200).complete)
    def test_out_of_range_holds(self):
        self.assertFalse(fetch_fills_window(Info([[{"time": 99, "tid": 1}]]), ADDR, 100, 200).complete)
    def test_exhaustion_holds(self):
        page = [{"time": 100, "tid": 1}]
        self.assertFalse(fetch_fills_window(Info([page]), ADDR, 100, 200, max_pages=1, page_limit=1).complete)

if __name__ == "__main__":
    unittest.main()
